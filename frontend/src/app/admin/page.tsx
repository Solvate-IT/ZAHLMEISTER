import {Suspense} from "react";
import {PlatformAdmin} from "@/components/PlatformAdmin";

export default function AdminPage(){
  return <Suspense fallback={null}><PlatformAdmin/></Suspense>;
}
