import {Suspense} from "react";
import {PlatformAdmin} from "@/components/PlatformAdmin";
import {Loading} from "@/components/State";

export default function AdminPage(){
  return <Suspense fallback={<div className="auth-wrap"><Loading/></div>}><PlatformAdmin/></Suspense>;
}
