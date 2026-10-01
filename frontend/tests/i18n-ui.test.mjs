import test from "node:test";
import assert from "node:assert/strict";
import {readdirSync,readFileSync,statSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";

const srcRoot=fileURLToPath(new URL("../src/",import.meta.url));
const moduleCatalogFiles=["admin.ts","billing.ts","integrations.ts","legal.ts","settings.ts","storeBilling.ts","ux.ts"];
const importantLocaleKeys=[
  "headline","subtitle","login","register","participantLists","collections","settings",
  "paymentLink","bankSync","onlinePayments","portalNavFeatures","portalNavHowItWorks",
  "portalStepOneTitle","portalStepTwoTitle","portalStepThreeTitle","portalTrustDirect",
];
const letter=/[A-Za-zÀ-ÖØ-öø-ÿĀ-ž]/u;

function filesBelow(dir,extensions){
  return readdirSync(dir).flatMap(name=>{
    const full=path.join(dir,name);
    return statSync(full).isDirectory()?filesBelow(full,extensions):extensions.some(ext=>full.endsWith(ext))?[full]:[];
  });
}

function read(relative){return readFileSync(path.join(srcRoot,relative),"utf8")}
function json(relative){return JSON.parse(read(relative))}

function bracedBody(source,braceIndex){
  let depth=0,quote="",escaped=false,lineComment=false,blockComment=false;
  for(let index=braceIndex;index<source.length;index++){
    const char=source[index],next=source[index+1];
    if(lineComment){if(char==="\n")lineComment=false;continue}
    if(blockComment){if(char==="*"&&next==="/"){blockComment=false;index++}continue}
    if(quote){
      if(escaped){escaped=false;continue}
      if(char==="\\"){escaped=true;continue}
      if(char===quote)quote="";
      continue;
    }
    if(char==="/"&&next==="/"){lineComment=true;index++;continue}
    if(char==="/"&&next==="*"){blockComment=true;index++;continue}
    if(char==='"'||char==="'"||char==='`'){quote=char;continue}
    if(char==="{")depth++;
    else if(char==="}"){
      depth--;
      if(depth===0)return source.slice(braceIndex+1,index);
    }
  }
  throw new Error("Unbalanced catalog object");
}

function localeBlock(source,locale){
  const marker=new RegExp(`\\b${locale}\\s*:\\s*\\{`).exec(source);
  if(!marker)return null;
  const brace=source.indexOf("{",marker.index);
  return bracedBody(source,brace);
}

function namedObject(source,name){
  const marker=source.indexOf(`const ${name}`);
  assert.notEqual(marker,-1,`Missing ${name}`);
  const brace=source.indexOf("{",marker);
  return bracedBody(source,brace);
}

function stringEntries(block){
  const entries=new Map();
  const pattern=/\b([A-Za-z_$][\w$]*)\s*:\s*"((?:\\.|[^"\\])*)"/g;
  for(const match of block.matchAll(pattern))entries.set(match[1],JSON.parse(`"${match[2]}"`));
  return entries;
}

function placeholders(value){
  return [...String(value).matchAll(/\{([A-Za-z0-9_]+)\}/g)].map(match=>match[1]).sort();
}

function supportedLocales(){
  const source=read("lib/i18n.tsx");
  const match=/const supported = \[([^\]]+)\] as const;/.exec(source);
  assert.ok(match,"Supported locale list not found");
  return [...match[1].matchAll(/"([a-z]{2})"/g)].map(item=>item[1]);
}

function billingProfileValues(locale){
  for(const file of ["locales/billingProfileA.ts","locales/billingProfileB.ts"]){
    const source=read(file);
    const match=new RegExp(`\\b${locale}\\s*:\\s*m\\(\\[([\\s\\S]*?)\\]\\)`).exec(source);
    if(match)return JSON.parse(`[${match[1]}]`);
  }
  return null;
}

function billingProfileKeys(){
  const shared=read("locales/billingProfileShared.ts");
  const match=/billingProfileKeys\s*=\s*\[([\s\S]*?)\]\s*as const/.exec(shared);
  assert.ok(match,"billingProfileKeys not found");
  return [...match[1].matchAll(/"([A-Za-z_$][\w$]*)"/g)].map(item=>item[1]);
}

function completeCatalog(locale){
  const entries=new Map();
  const origins=new Map();
  const add=(key,value,origin)=>{
    assert.equal(typeof value,"string",`${origin}:${key} must be a string`);
    assert.notEqual(value.trim(),"",`${origin}:${key} must not be empty`);
    if(entries.has(key))assert.equal(entries.get(key),value,`Conflicting ${locale} translation for ${key}: ${origins.get(key)} vs ${origin}`);
    else{entries.set(key,value);origins.set(key,origin)}
  };

  for(const [key,value] of Object.entries(json(`locales/${locale}.json`)))add(key,value,`${locale}.json`);
  for(const file of moduleCatalogFiles){
    const block=localeBlock(read(`locales/${file}`),locale);
    if(!block)continue;
    for(const [key,value] of stringEntries(block))add(key,value,file);
  }

  const profileKeys=billingProfileKeys();
  const profileValues=billingProfileValues(locale);
  if(profileValues){
    assert.equal(profileValues.length,profileKeys.length,`Billing profile catalog length mismatch for ${locale}`);
    profileKeys.forEach((key,index)=>add(key,profileValues[index],"billingProfile"));
  }

  const billing=read("locales/billing.ts");
  for(const [record,key] of [["billingInvoicePdfLabels","billingInvoicePdf"],["billingInvoicePreparingLabels","billingInvoicePreparing"]]){
    const valuesByLocale=stringEntries(namedObject(billing,record));
    if(valuesByLocale.has(locale))add(key,valuesByLocale.get(locale),record);
  }
  return entries;
}

function englishCatalog(){
  return completeCatalog("en");
}

function visibleLiteralIssues(source,file){
  const issues=[];
  const direct=/<([A-Za-z][A-Za-z0-9.-]*)([^<>]*)>([^<>{}]*)<\/\1>/g;
  for(const match of source.matchAll(direct)){
    const [,tag,attributes,body]=match;
    const value=body.replace(/\s+/g," ").trim();
    if(!value||!letter.test(value))continue;
    if(/^(code|pre)$/i.test(tag)||/\bclassName\s*=\s*["'][^"']*\bcode(?:-inline)?\b[^"']*["']/.test(attributes))continue;
    issues.push(`${file}: hard-coded JSX text "${value}"`);
  }
  const attributes=/\b(placeholder|title|aria-label|alt)\s*=\s*["']([^"']*)["']/g;
  for(const match of source.matchAll(attributes))if(letter.test(match[2]))issues.push(`${file}: hard-coded ${match[1]} "${match[2]}"`);
  const setters=/\b(setNotice|setError|setVerificationNotice)\(\s*["']([^"']*)["']\s*\)/g;
  for(const match of source.matchAll(setters))if(letter.test(match[2]))issues.push(`${file}: hard-coded ${match[1]} message "${match[2]}"`);
  const toast=/\bshowToast\s*\(\s*\{\s*message\s*:\s*["']([^"']*)["']/g;
  for(const match of source.matchAll(toast))if(letter.test(match[1]))issues.push(`${file}: hard-coded toast "${match[1]}"`);
  return issues;
}

test("visible JSX copy uses the existing i18n layer",()=>{
  const issues=[];
  for(const file of filesBelow(srcRoot,[".tsx"])){
    issues.push(...visibleLiteralIssues(readFileSync(file,"utf8"),path.relative(srcRoot,file)));
  }
  assert.deepEqual(issues,[]);
});

test("every statically used translation key exists in the English catalog",()=>{
  const english=englishCatalog();
  const missing=[];
  for(const file of filesBelow(srcRoot,[".tsx"])){
    const source=readFileSync(file,"utf8");
    for(const match of source.matchAll(/\bt\(\s*["']([^"']+)["']/g)){
      if(!english.has(match[1]))missing.push(`${path.relative(srcRoot,file)}: ${match[1]}`);
    }
  }
  assert.deepEqual(missing,[]);
});

test("English catalog entries are non-empty and non-conflicting",()=>{
  assert.ok(englishCatalog().size>0);
});

test("catalogs do not contain contradictory duplicate translations",()=>{
  for(const locale of supportedLocales())assert.ok(completeCatalog(locale).size>0);
});

test("dynamic template translation keys use only explicitly supported patterns",()=>{
  const english=englishCatalog();
  const supportedPatterns=new Set([
    "terms_${section}_title",
    "terms_${section}_body",
    "${provider}OnboardingTitle",
    "${provider}OnboardingHint",
  ]);
  const issues=[];
  for(const file of filesBelow(srcRoot,[".tsx"])){
    const text=readFileSync(file,"utf8");
    for(const match of text.matchAll(/\bt\(\s*`([^`]*)`/g)){
      if(!match[1].includes("${"))continue;
      if(!supportedPatterns.has(match[1]))issues.push(`${path.relative(srcRoot,file)}: ${match[1]}`);
    }
  }
  assert.deepEqual(issues,[]);

  const legal=read("locales/legal.ts");
  const sectionsMatch=/TERMS_SECTIONS\s*=\s*\[([\s\S]*?)\]\s*as const/.exec(legal);
  assert.ok(sectionsMatch,"TERMS_SECTIONS not found");
  const sections=[...sectionsMatch[1].matchAll(/"([^"]+)"/g)].map(match=>match[1]);
  for(const section of sections){
    assert.ok(english.has(`terms_${section}_title`),`Missing English terms_${section}_title`);
    assert.ok(english.has(`terms_${section}_body`),`Missing English terms_${section}_body`);
  }

  for(const provider of ["infobip","mollie","ponto"]){
    assert.ok(english.has(`${provider}OnboardingTitle`),`Missing English ${provider}OnboardingTitle`);
    assert.ok(english.has(`${provider}OnboardingHint`),`Missing English ${provider}OnboardingHint`);
  }
});

test("placeholders remain compatible across locale catalogs",()=>{
  const locales=supportedLocales();
  const englishJson=json("locales/en.json");
  for(const locale of locales){
    const messages=json(`locales/${locale}.json`);
    for(const [key,value] of Object.entries(messages)){
      if(!(key in englishJson))continue;
      assert.deepEqual(placeholders(value),placeholders(englishJson[key]),`${locale}.json:${key} changes placeholders`);
    }
  }
  for(const file of moduleCatalogFiles){
    const source=read(`locales/${file}`);
    const englishBlock=localeBlock(source,"en");
    assert.ok(englishBlock,`${file} has no English catalog`);
    const english=stringEntries(englishBlock);
    for(const locale of locales){
      const block=localeBlock(source,locale);
      if(!block)continue;
      for(const [key,value] of stringEntries(block)){
        if(!english.has(key))continue;
        assert.deepEqual(placeholders(value),placeholders(english.get(key)),`${file}:${locale}:${key} changes placeholders`);
      }
    }
  }
  const englishProfile=billingProfileValues("en");
  assert.ok(englishProfile);
  for(const locale of locales){
    const values=billingProfileValues(locale);
    assert.ok(values,`Missing billing profile catalog for ${locale}`);
    assert.equal(values.length,englishProfile.length,`Billing profile catalog length mismatch for ${locale}`);
    values.forEach((value,index)=>assert.deepEqual(placeholders(value),placeholders(englishProfile[index]),`billingProfile:${locale}:${index} changes placeholders`));
  }
});

test("important product copy exists in every supported locale",()=>{
  for(const locale of supportedLocales()){
    const messages=json(`locales/${locale}.json`);
    for(const key of importantLocaleKeys){
      assert.equal(typeof messages[key],"string",`${locale}.json is missing ${key}`);
      assert.notEqual(messages[key].trim(),"",`${locale}.json has an empty ${key}`);
    }
  }
});

test("locale resolution exhausts the selected language before English fallback",()=>{
  const source=read("lib/i18n.tsx");
  assert.match(source,/const localizedCatalogs/);
  assert.match(source,/const fallbackCatalogs/);
  assert.doesNotMatch(source,/Messages\[locale\]\s*\?\?\s*\w+Messages\.en/);
  assert.match(source,/document\.documentElement\.lang=locale/);
});

test("English base catalog contains no known German carry-overs",()=>{
  const messages=json("locales/en.json");
  assert.equal(messages.createdAt,"Created at");
  assert.equal(messages.filename,"File");
  assert.equal(messages.contactLists,"Contact lists");
  assert.equal(messages.collection,"Collection");
  assert.equal(messages.importFile,"Import file");
  assert.equal(messages.communicationSettings,"Communication");
  assert.equal(messages.paymentSettings,"Payment account");
  assert.equal(messages.onlinePaymentSettings,"Online payments");
  assert.equal(messages.closeDialog,"Close dialog");
  assert.equal(messages.privacy,"Privacy");
  assert.equal(messages.imprint,"Legal notice");
  assert.equal(messages.languageFallback,"Untranslated text is shown in English.");
});

test("static metadata uses the translation catalog",()=>{
  const source=read("app/layout.tsx");
  assert.match(source,/title: de\.appName/);
  assert.match(source,/description: de\.subtitle/);
});
