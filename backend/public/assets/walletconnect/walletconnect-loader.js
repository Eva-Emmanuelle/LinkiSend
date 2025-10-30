// backend/public/assets/walletconnect/walletconnect-loader.js
(async () => {
  if (!window.WalletConnectSignClient) {
    const module = await import("https://esm.sh/@walletconnect/sign-client@2.11.2");
    window.WalletConnectSignClient = module.default;
    console.log("WalletConnectSignClient prêt ✅");
  }
})();
