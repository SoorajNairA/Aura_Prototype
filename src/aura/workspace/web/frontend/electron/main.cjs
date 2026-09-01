const {app,BrowserWindow,ipcMain,shell}=require("electron");
const path=require("node:path");
const http=require("node:http");

const apiUrl=(process.env.AURA_API_URL||"http://127.0.0.1:8765").replace(/\/$/,"");
const wsUrl=(process.env.AURA_WS_URL||apiUrl.replace(/^http/,"ws")).replace(/\/$/,"");
if(process.argv.includes("--smoke")||process.argv.includes("--smoke-recovery"))app.setPath("userData",path.join(app.getPath("temp"),"aura-electron-smoke"));
let mainWindow;
let backendPoll;
function backendReady(){return new Promise(resolve=>{const request=http.get(`${apiUrl}/health/live`,response=>{response.resume();resolve(response.statusCode===200)});request.setTimeout(1500,()=>{request.destroy();resolve(false)});request.on("error",()=>resolve(false))})}
function waitForBackend(startUrl){
 clearTimeout(backendPoll);
 const poll=async()=>{if(!mainWindow||mainWindow.isDestroyed())return;if(await backendReady()){backendPoll=undefined;await mainWindow.loadURL(startUrl)}else backendPoll=setTimeout(poll,1000)};
 backendPoll=setTimeout(poll,1000);
}
async function createWindow(){
 mainWindow=new BrowserWindow({width:1600,height:960,minWidth:1080,minHeight:680,backgroundColor:"#02070d",show:false,title:"AURA Engineering Workspace",webPreferences:{preload:path.join(__dirname,"preload.cjs"),nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true}});
 mainWindow.removeMenu();mainWindow.webContents.setWindowOpenHandler(({url})=>{if(/^https:\/\//.test(url))shell.openExternal(url);return{action:"deny"}});
 mainWindow.webContents.on("will-navigate",(event,url)=>{if(!url.startsWith(apiUrl))event.preventDefault()});
 mainWindow.webContents.on("did-fail-load",(_event,code,description,url,isMainFrame)=>{if(isMainFrame)console.error(`AURA_ELECTRON_LOAD_FAILED ${code} ${description} ${url}`)});
 mainWindow.webContents.on("render-process-gone",(_event,details)=>console.error(`AURA_ELECTRON_RENDERER_GONE ${details.reason} ${details.exitCode}`));
 mainWindow.webContents.on("console-message",details=>{if(details.level==="error")console.error(`AURA_ELECTRON_RENDERER_ERROR ${details.message}`)});
 mainWindow.once("ready-to-show",()=>mainWindow.show());
 mainWindow.webContents.on("did-finish-load",()=>{const online=mainWindow.webContents.getURL().startsWith(apiUrl);if(process.argv.includes("--smoke-recovery")){if(online){console.log("AURA_ELECTRON_RECOVERY_PASS");setTimeout(()=>app.quit(),250)}else console.log("AURA_ELECTRON_OFFLINE_SHELL")}else if(process.argv.includes("--smoke")){console.log("AURA_ELECTRON_SMOKE_PASS");setTimeout(()=>app.quit(),250)}});
 const startUrl=apiUrl;
 if(await backendReady()) await mainWindow.loadURL(startUrl);
 else {console.log("AURA_BACKEND_OFFLINE: backend was not started; loading offline shell.");await mainWindow.loadFile(path.join(__dirname,"offline.html"));waitForBackend(startUrl);}
}
ipcMain.handle("aura:window",(_event,action)=>{if(!mainWindow)return false;if(action==="minimize")mainWindow.minimize();else if(action==="maximize")mainWindow.isMaximized()?mainWindow.unmaximize():mainWindow.maximize();else if(action==="close")mainWindow.close();else return false;return true});
app.whenReady().then(createWindow);app.on("window-all-closed",()=>{clearTimeout(backendPoll);app.quit()});
