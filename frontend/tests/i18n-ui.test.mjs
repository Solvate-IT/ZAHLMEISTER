import test from "node:test";
import assert from "node:assert/strict";
import {readdirSync,readFileSync,statSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";
import ts from "typescript";

const srcRoot=fileURLToPath(new URL("../src/",import.meta.url));

function tsxFiles(dir){
  return readdirSync(dir).flatMap(name=>{
    const full=path.join(dir,name);
    return statSync(full).isDirectory()?tsxFiles(full):full.endsWith(".tsx")?[full]:[];
  });
}

function codeContainer(node,sourceFile){
  let current=node.parent;
  while(current){
    if(ts.isJsxElement(current)){
      const opening=current.openingElement;
      const tag=opening.tagName.getText(sourceFile);
      if(tag==="code"||tag==="pre")return true;
      for(const attr of opening.attributes.properties){
        if(!ts.isJsxAttribute(attr)||attr.name.getText(sourceFile)!=="className"||!attr.initializer||!ts.isStringLiteral(attr.initializer))continue;
        if(/(^|\s)code(?:-inline)?(\s|$)/.test(attr.initializer.text))return true;
      }
    }
    current=current.parent;
  }
  return false;
}

test("visible JSX copy goes through i18n",()=>{
  const issues=[];
  for(const file of tsxFiles(srcRoot)){
    const source=readFileSync(file,"utf8");
    const sf=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
    const visit=node=>{
      if(ts.isJsxText(node)){
        const value=node.getText(sf).replace(/\s+/g," ").trim();
        if(value&&/[A-Za-zÀ-ž]/u.test(value)&&!codeContainer(node,sf)){
          issues.push(`${path.relative(srcRoot,file)}: hard-coded JSX text "${value}"`);
        }
      }
      if(ts.isJsxAttribute(node)){
        const name=node.name.getText(sf);
        if(["aria-label","title","placeholder","alt"].includes(name)&&node.initializer&&ts.isStringLiteral(node.initializer)&&/[A-Za-zÀ-ž]/u.test(node.initializer.text)){
          issues.push(`${path.relative(srcRoot,file)}: hard-coded ${name} "${node.initializer.text}"`);
        }
      }
      ts.forEachChild(node,visit);
    };
    visit(sf);
  }
  assert.deepEqual(issues,[]);
});

test("locale resolution exhausts the selected language before English fallback",()=>{
  const source=readFileSync(path.join(srcRoot,"lib/i18n.tsx"),"utf8");
  assert.match(source,/const localizedCatalogs/);
  assert.match(source,/const fallbackCatalogs/);
  assert.doesNotMatch(source,/Messages\[locale\]\s*\?\?\s*\w+Messages\.en/);
  assert.match(source,/document\.documentElement\.lang=locale/);
});

test("English base catalog contains no known German carry-overs",()=>{
  const messages=JSON.parse(readFileSync(path.join(srcRoot,"locales/en.json"),"utf8"));
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
  const source=readFileSync(path.join(srcRoot,"app/layout.tsx"),"utf8");
  assert.match(source,/title: de\.appName/);
  assert.match(source,/description: de\.subtitle/);
});
