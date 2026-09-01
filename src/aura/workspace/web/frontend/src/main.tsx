import {Component,ErrorInfo,ReactNode} from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { WorkspaceApp } from "./WorkspaceApp";

class WorkspaceErrorBoundary extends Component<{children:ReactNode},{failed:boolean}>{
 state={failed:false};
 static getDerivedStateFromError(){return{failed:true}}
 componentDidCatch(error:Error,info:ErrorInfo){console.error("AURA workspace renderer failed",error,info.componentStack)}
 render(){if(this.state.failed)return <main className="aura-shell welcome"><div className="ambient-grid"/><section className="welcome-core"><div className="aura-mark">AURA</div><p>AI ENGINEERING WORKSPACE</p><h1>The workspace could not be displayed.</h1><span className="quiet-status">Reset the saved session and return to the project launcher.</span><div className="examples"><button onClick={()=>{localStorage.removeItem("aura:last-project");location.assign(location.pathname)}}>RESET WORKSPACE</button></div></section></main>;return this.props.children}
}

createRoot(document.getElementById("root")!).render(<WorkspaceErrorBoundary><WorkspaceApp /></WorkspaceErrorBoundary>);
