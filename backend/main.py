import json
import os
import re
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import shortuuid

app = FastAPI()

# CORS pour autoriser le frontend (port 8001)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Chemins de données (fixés dans backend/data) ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

LINKS_FILE = os.path.join(DATA_DIR, "links.json")
TRANSACTIONS_FILE = os.path.join(DATA_DIR, "transactions.json")

# ---------- Modèles ----------
class LinkData(BaseModel):
    amount: float
    currency: str
    sender_wallet: str
    recipient_phone: str
    network: str

class ClaimData(BaseModel):
    short_id: str = Field(..., description="Identifiant court du lien")
    recipient_phone: str = Field(..., description="Téléphone saisi par le receveur")
    recipient_wallet: str = Field(..., description="Wallet EVM du receveur (0x...)")

# ---------- Helpers JSON ----------
def load_links():
    if not os.path.exists(LINKS_FILE):
        return {}
    with open(LINKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_links(links):
    with open(LINKS_FILE, "w", encoding="utf-8") as f:
        json.dump(links, f, indent=2, ensure_ascii=False)

def load_transactions():
    if not os.path.exists(TRANSACTIONS_FILE):
        return []
    with open(TRANSACTIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_transactions(transactions):
    with open(TRANSACTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(transactions, f, indent=2, ensure_ascii=False)

def add_transaction(entry: dict):
    txs = load_transactions()
    txs.append(entry)
    save_transactions(txs)

# ---------- Nettoyage / Expiration ----------
def is_expired(link: dict) -> bool:
    created_at = datetime.fromisoformat(link["created_at"])
    return created_at <= datetime.utcnow() - timedelta(hours=24)

def clean_links():
    """
    GARDE :
      - tous les liens réclamés (claimed=True)
      - les liens non réclamés encore valides (<24h)
    SUPPRIME :
      - uniquement les liens non réclamés ET expirés (>24h)
    """
    links = load_links()
    now = datetime.utcnow()
    updated = {}
    for link_id, data in links.items():
        created_at = datetime.fromisoformat(data["created_at"])
        claimed = data.get("claimed", False)
        expired = created_at <= now - timedelta(hours=24)
        if (not claimed) and expired:
            continue  # on supprime seulement les non réclamés expirés
        updated[link_id] = data
    save_links(updated)

# ---------- Validations simples ----------
EVM_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

def phone_ok(phone: str) -> bool:
    s = (phone or "").strip()
    if not s:
        return False
    if not re.match(r"^\+?[0-9\s\-().]{6,}$", s):
        return False
    digits = re.sub(r"\D", "", s)
    return len(digits) >= 6

def evm_ok(addr: str) -> bool:
    return bool(EVM_ADDR_RE.match((addr or "").strip()))

# ---------- API ----------
@app.post("/create-link")
def create_link(data: LinkData):
    clean_links()
    links = load_links()

    link_id = shortuuid.uuid()
    short_id = shortuuid.uuid()[:6]
    now_str = datetime.utcnow().isoformat()

    links[link_id] = {
        "amount": data.amount,
        "currency": data.currency,
        "sender_wallet": data.sender_wallet,
        "recipient_phone": data.recipient_phone,
        "network": data.network,
        "created_at": now_str,
        "claimed": False,
        "short_id": short_id
    }
    save_links(links)

    add_transaction({
        "event": "create",
        "link_id": link_id,
        "short_id": short_id,
        "amount": data.amount,
        "currency": data.currency,
        "sender_wallet": data.sender_wallet,
        "recipient_phone": data.recipient_phone,
        "network": data.network,
        "created_at": now_str
    })

    return {"link_id": link_id, "short_id": short_id}

@app.post("/claim")
def claim_link(data: ClaimData):
    """Réclamer via short_id + vérification téléphone + wallet receveur (obligatoire)."""
    links = load_links()

    # Retrouver le lien par short_id
    link_id = None
    link = None
    for k, v in links.items():
        if v.get("short_id") == data.short_id:
            link_id, link = k, v
            break

    if not link:
        raise HTTPException(status_code=404, detail="Lien invalide, expiré ou déjà utilisé")

    # Statut/expiration
    if link.get("claimed", False) or is_expired(link):
        raise HTTPException(status_code=400, detail="Lien invalide, expiré ou déjà utilisé")

    # Vérifs côté serveur
    if not phone_ok(data.recipient_phone):
        raise HTTPException(status_code=400, detail="Numéro invalide.")
    if (data.recipient_phone or "").strip() != (link.get("recipient_phone") or "").strip():
        raise HTTPException(status_code=400, detail="Le numéro ne correspond pas à ce lien.")
    if not evm_ok(data.recipient_wallet):
        raise HTTPException(status_code=400, detail="Wallet invalide (format EVM 0x...).")

    # Marquer comme réclamé + enregistrer le wallet receveur
    link["claimed"] = True
    link["claimed_at"] = datetime.utcnow().isoformat()
    link["recipient_wallet"] = data.recipient_wallet
    links[link_id] = link
    save_links(links)

    # --- SIMULATION D'ENVOI ON-CHAIN (log + faux tx hash) ---
    fake_tx_hash = "0x" + secrets.token_hex(32)
    print(
        f"[SIMULATION] Sending {link['amount']} {link['currency']} "
        f"from {link['sender_wallet']} to {data.recipient_wallet} "
        f"on {link['network']} (short_id={link.get('short_id')})"
    )
    print(f"[SIMULATION] Fake tx hash: {fake_tx_hash}")

    add_transaction({
        "event": "claim",
        "link_id": link_id,
        "short_id": link.get("short_id"),
        "amount": link["amount"],
        "currency": link["currency"],
        "sender_wallet": link["sender_wallet"],
        "recipient_phone": link["recipient_phone"],
        "recipient_wallet": data.recipient_wallet,
        "network": link["network"],
        "created_at": link["created_at"],
        "claimed_at": link["claimed_at"],
        "sim_tx_hash": fake_tx_hash
    })

    clean_links()
    return {"status": "success", "sim_tx_hash": fake_tx_hash}

@app.get("/s/{short_id}")
def redirect_short_link(short_id: str):
    """Lien court -> redirection vers le frontend avec ?sid=..."""
    links = load_links()
    for link in links.values():
        if link.get("short_id") == short_id:
            frontend = os.getenv("FRONTEND_URL", "https://linkisend.onrender.com")
            return RedirectResponse(url=f"{frontend}/claim.html?sid={short_id}")
    raise HTTPException(status_code=404, detail="Lien invalide, expiré ou déjà utilisé")

@app.get("/api/short-link/{short_id}")
def get_link_by_short_id(short_id: str):
    """Détails non sensibles pour le front (utiles si besoin)."""
    links = load_links()
    for link in links.values():
        if link.get("short_id") == short_id:
            if is_expired(link):
                raise HTTPException(status_code=400, detail="Lien invalide, expiré ou déjà utilisé")
            return {
                "amount": link["amount"],
                "currency": link["currency"],
                "network": link["network"],
                "created_at": link["created_at"],
                "claimed": link.get("claimed", False)
            }
    raise HTTPException(status_code=404, detail="Lien invalide, expiré ou déjà utilisé")

# ---------- Historique (vue expéditeur) ----------
@app.get("/api/history")
def api_history():
    links = load_links()
    txs = load_transactions()

    claims_by_link = {}
    for tx in txs:
        if tx.get("event") == "claim":
            claims_by_link[tx["link_id"]] = tx

    items = []
    for link_id, lk in links.items():
        claim_tx = claims_by_link.get(link_id)
        items.append({
            "short_id": lk.get("short_id"),
            "amount": lk["amount"],
            "currency": lk["currency"],
            "network": lk["network"],
            "created_at": lk["created_at"],
            "claimed": lk.get("claimed", False),
            "claimed_at": lk.get("claimed_at"),
            "recipient_phone": lk.get("recipient_phone"),
            "recipient_wallet": lk.get("recipient_wallet"),
            "sender_wallet": lk.get("sender_wallet"),
            "sim_tx_hash": (claim_tx or {}).get("sim_tx_hash")
        })

    def parse_iso(ts):
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return datetime.min

    items.sort(key=lambda x: parse_iso(x.get("created_at") or ""), reverse=True)
    return {"items": items}

@app.get("/link/{link_id}")
def get_link(link_id: str):
    links = load_links()
    if link_id in links:
        if is_expired(links[link_id]):
            raise HTTPException(status_code=400, detail="Lien invalide, expiré ou déjà utilisé")
        return links[link_id]
    raise HTTPException(status_code=404, detail="Lien invalide, expiré ou déjà utilisé")
