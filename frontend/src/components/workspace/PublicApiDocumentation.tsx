"use client";

import {useI18n} from "@/lib/i18n";

const endpoints=[
  ["GET","/participant-lists","participants:read","apiEndpointListParticipantLists"],
  ["POST","/participant-lists","participants:write","apiEndpointCreateParticipantList"],
  ["GET","/participant-lists/{list_id}","participants:read","apiEndpointParticipantListDetail"],
  ["POST","/participant-lists/{list_id}/participants","participants:write","apiEndpointAddParticipant"],
  ["GET","/collections","collections:read","apiEndpointListCollections"],
  ["POST","/collections","collections:write","apiEndpointCreateCollection"],
  ["GET","/collections/{collection_id}","collections:read","apiEndpointCollectionDetail"],
  ["GET","/collections/{collection_id}/status","payments:read","apiEndpointCollectionStatus"],
] as const;

export function PublicApiDocumentation(){
  const {t}=useI18n();
  return <section className="card">
    <h3>{t("publicApiDocsTitle")}</h3>
    <p className="muted">{t("publicApiDocsIntro")}</p>
    <div className="stack">
      <div><strong>{t("publicApiBaseUrl")}</strong><div className="code">/api/public/v1</div></div>
      <div><strong>{t("publicApiAuthentication")}</strong><p className="muted">{t("publicApiAuthenticationHint")}</p><div className="code">Authorization: Bearer &lt;API_KEY&gt;</div></div>
      <div><strong>{t("publicApiScopes")}</strong><p className="muted">{t("publicApiScopesHint")}</p></div>
      <div>
        <strong>{t("publicApiEndpoints")}</strong>
        <div className="table-wrap" style={{marginTop:8}}><table className="table"><thead><tr><th>{t("publicApiMethod")}</th><th>{t("publicApiPath")}</th><th>{t("apiScopes")}</th><th>{t("details")}</th></tr></thead><tbody>{endpoints.map(([method,path,scope,key])=><tr key={`${method}-${path}`}><td><strong>{method}</strong></td><td className="code-inline">{path}</td><td className="code-inline">{scope}</td><td>{t(key)}</td></tr>)}</tbody></table></div>
      </div>
      <div><strong>{t("publicApiExample")}</strong><pre className="code" style={{whiteSpace:"pre-wrap",margin:0}}>{`curl -H "Authorization: Bearer <API_KEY>" \\\n  https://YOUR-ZAHLMEISTER-HOST/api/public/v1/collections/{collection_id}/status`}</pre></div>
      <div><strong>{t("publicApiCreateExample")}</strong><pre className="code" style={{whiteSpace:"pre-wrap",margin:0}}>{`POST /api/public/v1/collections\nContent-Type: application/json\nAuthorization: Bearer <API_KEY>\n\n{\n  "participant_list_id": "<UUID>",\n  "name": "Collection name",\n  "amount": "45.00",\n  "currency": "EUR",\n  "communication_channel": "auto"\n}`}</pre></div>
      <div><strong>{t("publicApiErrors")}</strong><p className="muted">{t("publicApiErrorsHint")}</p></div>
    </div>
  </section>
}
