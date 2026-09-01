const {contextBridge,ipcRenderer}=require("electron");
contextBridge.exposeInMainWorld("auraDesktop",Object.freeze({
 platform:"desktop",
 apiUrl:(process.env.AURA_API_URL||"http://127.0.0.1:8765").replace(/\/$/,""),
 wsUrl:(process.env.AURA_WS_URL||(process.env.AURA_API_URL||"http://127.0.0.1:8765").replace(/^http/,"ws")).replace(/\/$/,""),
 window:Object.freeze({minimize:()=>ipcRenderer.invoke("aura:window","minimize"),maximize:()=>ipcRenderer.invoke("aura:window","maximize"),close:()=>ipcRenderer.invoke("aura:window","close")})
}));
