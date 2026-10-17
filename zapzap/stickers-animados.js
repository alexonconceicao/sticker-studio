// Stickers animados no ZapZap: colar (Ctrl+V) ou soltar um .webp na conversa
// envia como figurinha em vez de imagem. Segure Shift ao soltar pra enviar como imagem.
// Baseado no envio de figurinha do whatsapp-web.js (WAWebUploadManager + addAndSendMsgToChat).
(function () {
  if (window.__stickersAnimados) return;
  window.__stickersAnimados = true;

  const req = (m) => window.require(m);

  function toast(text, ok = true) {
    const el = document.createElement("div");
    el.textContent = text;
    Object.assign(el.style, {
      position: "fixed", bottom: "24px", left: "50%", transform: "translateX(-50%)", zIndex: 99999,
      padding: "10px 18px", borderRadius: "8px", font: "14px system-ui, sans-serif", color: "#fff",
      background: ok ? "#1f7a4d" : "#a33", boxShadow: "0 4px 16px rgba(0,0,0,.3)",
    });
    document.body.appendChild(el);
    setTimeout(() => el.remove(), ok ? 2000 : 6000);
  }

  function activeChat() {
    const Chat = req("WAWebCollections").Chat;
    return (Chat.getActive && Chat.getActive()) || (Chat.getModelsArray ? Chat.getModelsArray() : Chat.models || []).find((c) => c.active);
  }

  async function sha256b64(file) {
    const hash = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    return btoa(String.fromCharCode(...new Uint8Array(hash)));
  }

  function randomKey(n) {
    const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    const rnd = crypto.getRandomValues(new Uint8Array(n));
    return Array.from(rnd, (b) => chars[b % chars.length]).join("");
  }

  async function sendSticker(file) {
    const chat = activeChat();
    if (!chat) throw new Error("abra uma conversa primeiro");

    const filehash = await sha256b64(file);
    const uploaded = await req("WAWebUploadManager").encryptAndUpload({
      blob: file,
      type: "sticker",
      signal: new AbortController().signal,
      mediaKey: randomKey(32),
      uploadQpl: req("WAWebStartMediaUploadQpl").startMediaUploadQpl({ entryPoint: "MediaUpload" }),
    });

    const { getMaybeMeLidUser, getMaybeMePnUser } = req("WAWebUserPrefsMeUser");
    const WidFactory = req("WAWebWidFactory");
    const MsgKey = req("WAWebMsgKey");
    let from = chat.id.isLid && chat.id.isLid() ? getMaybeMeLidUser() : getMaybeMePnUser();
    let participant;
    if (chat.id.isGroup && chat.id.isGroup()) {
      from = chat.groupMetadata && chat.groupMetadata.isLidAddressingMode ? getMaybeMeLidUser() : getMaybeMePnUser();
      participant = WidFactory.asUserWidOrThrow(from);
    }
    const id = new MsgKey({ from, to: chat.id, id: await MsgKey.newId(), participant, selfDir: "out" });

    const message = {
      id, ack: 0, body: undefined, from, to: chat.id, local: true, self: "out",
      t: Math.floor(Date.now() / 1000), isNewMsg: true,
      ...req("WAWebGetEphemeralFieldsMsgActionsUtils").getEphemeralFields(chat),
      ...uploaded,
      clientUrl: uploaded.url,
      deprecatedMms3Url: uploaded.url,
      uploadhash: uploaded.encFilehash,
      size: file.size,
      filehash,
      mimetype: "image/webp",
      type: "sticker",
    };
    const [msgPromise] = req("WAWebSendMsgChatAction").addAndSendMsgToChat(chat, message);
    await msgPromise;
  }

  const isWebp = (f) => f && (f.type === "image/webp" || /\.webp$/i.test(f.name || ""));

  async function handle(e, files) {
    const webps = Array.from(files || []).filter(isWebp);
    if (!webps.length || webps.length !== (files || []).length) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    for (const f of webps) {
      try {
        await sendSticker(f);
        toast("Figurinha enviada");
      } catch (err) {
        console.error("[stickers]", err);
        toast("Figurinha falhou: " + (err && err.message ? err.message : err), false);
      }
    }
  }

  window.addEventListener("paste", (e) => handle(e, e.clipboardData && e.clipboardData.files), true);
  window.addEventListener("drop", (e) => { if (!e.shiftKey) handle(e, e.dataTransfer && e.dataTransfer.files); }, true);
})();
