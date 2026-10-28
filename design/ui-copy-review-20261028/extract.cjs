const fs=require('fs'),path=require('path'),{createRequire}=require('module');
const requireFrontend=createRequire(path.resolve('frontend/package.json'));const {parse}=requireFrontend('@babel/parser');
const root=path.resolve('frontend/src'), out=__dirname;
const pages={App:'全局 / 登录 / 工作概览',AndroidPage:'手机工作台',AndroidApps:'手机 / 初始化与应用',AndroidCompanion:'手机 / 任务设置 / 浏览兴趣与公开互动',AndroidLive:'手机 / 实时画面',ConfigurationPages:'角色与群聊',GroupChatSettings:'角色与群聊 / Owner 与群聊参与',ConnectionPage:'连接与模型 / QQ 连接',ProvidersPage:'共享供应商 / 模型分配',MemoryModelSelectors:'连接与模型 / 记忆模型',MemoryPage:'角色记忆',SchedulePage:'每日日程',ScheduleChanges:'每日日程 / 修改记录',DiaryPage:'私人日记',ProactivePage:'主动互动',QzonePage:'主动互动 / QQ 空间',MemesPage:'表情素材',ChatsPage:'会话记录',LogsPage:'运行日志',BotsPage:'机器人管理',QQConnectDialog:'机器人管理 / 扫码添加',UserScopeSelector:'记忆与日程 / 用户范围',ThemeSelector:'全局 / 主题',main:'全局 / 404 页面',FeatureSearch:'全局 / 功能查找',BotNavigation:'全局 / 导航'};
const files=[];function gather(p){for(const d of fs.readdirSync(p,{withFileTypes:true})){const f=path.join(p,d.name);if(d.isDirectory())gather(f);else if(/\.(jsx|js)$/.test(f))files.push(f)}}gather(root);
let entries=[];
function tag(n){return n?.type==='JSXIdentifier'?n.name:n?.type==='JSXMemberExpression'?tag(n.object)+'.'+tag(n.property):''}
for(const file of files.sort()){
 const source=fs.readFileSync(file,'utf8'),ast=parse(source,{sourceType:'module',plugins:['jsx']});const parents=new WeakMap(),claimed=new Set();
 function children(n){return Object.values(n).flatMap(v=>Array.isArray(v)?v:[v]).filter(v=>v&&typeof v==='object'&&typeof v.type==='string')}
 function index(n){for(const c of children(n)){parents.set(c,n);index(c)}}index(ast);
 const raw=n=>source.slice(n.start,n.end);
 function expr(n){if(!n)return '';switch(n.type){case 'StringLiteral':return n.value;case 'JSXText':return n.value.replace(/\s+/g,' ');case 'JSXExpressionContainer':return expr(n.expression);case 'TemplateLiteral':return n.quasis.map((q,i)=>q.value.cooked+(n.expressions[i]?'〔'+raw(n.expressions[i])+'〕':'')).join('');case 'ConditionalExpression':return [...new Set([expr(n.consequent),expr(n.alternate)].filter(Boolean))].join(' / ');case 'LogicalExpression':return expr(n.right);case 'BinaryExpression':if(n.operator==='+')return expr(n.left)+expr(n.right);break;case 'JSXElement':return n.children.map(expr).join('');case 'JSXFragment':return n.children.map(expr).join('');case 'NumericLiteral':return String(n.value);case 'NullLiteral':case 'BooleanLiteral':case 'JSXEmptyExpression':return '';}
 return '〔'+raw(n).replace(/\s+/g,' ').slice(0,120)+'〕';}
 function attr(n,key){return n?.openingElement?.attributes?.find(a=>a.type==='JSXAttribute'&&a.name.name===key)?.value}
 function hasText(n){if(!n)return false;if(n.type==='StringLiteral'||n.type==='JSXText')return /[\u3400-\u9fffA-Za-z]/.test(n.value);if(n.type==='TemplateLiteral')return n.quasis.some(q=>/[\u3400-\u9fffA-Za-z]/.test(q.value.cooked||''));if(n.type==='ConditionalExpression')return hasText(n.consequent)||hasText(n.alternate);if(n.type==='LogicalExpression')return hasText(n.right);if(n.type==='JSXExpressionContainer')return hasText(n.expression);if(['JSXElement','JSXFragment'].includes(n.type))return n.children.some(hasText);if(n.type==='BinaryExpression')return hasText(n.left)||hasText(n.right);return false}
 function context(n){const items=[];let p=n;while(p){if(p.type==='JSXElement'){let t=attr(p,'title')||attr(p,'label');if(t&&hasText(t))items.unshift(expr(t));if(tag(p.openingElement.name)==='Dialog.Content'){const title=p.children.find(c=>c.type==='JSXElement'&&tag(c.openingElement.name)==='Dialog.Title');if(title)items.unshift(expr(title));}}p=parents.get(p)}return [...new Set(items)].join(' → ')}
 function claim(n){if(n.type==='StringLiteral'||n.type==='JSXText'||n.type==='TemplateElement')claimed.add(n.start);for(const c of children(n))claim(c)}
 function add(n,type,text,location,mark=true){text=(text??expr(n)).trim().replace(/\n\s+/g,'\n');if(!text||!hasText(n))return;entries.push({page:pages[path.basename(file,path.extname(file))]||'共享组件',location:location||context(n)||path.basename(file),type,text,file:path.relative(path.resolve('.'),file),line:n.loc.start.line,column:n.loc.start.column+1,visibility:(()=>{let p=n;while(p){if(p.type==='JSXAttribute'&&p.name.name==='aria-label')return '辅助访问名称';if(p.type==='JSXElement'&&attr(p,'className')?.value?.includes('sr-only'))return '辅助访问（视觉隐藏）';p=parents.get(p)}return '界面或条件显示'})(),start:n.start,end:n.end});if(mark)claim(n)}
 function walk(n){
  if(n.type==='CallExpression'&&n.callee.type==='MemberExpression'&&n.callee.property.name==='map'&&n.callee.object.type==='ArrayExpression'){
   const fn=n.arguments[0],pattern=fn?.params?.[0];
   if(pattern?.type==='ArrayPattern')for(const key of ['hint','detail','k']){
    const i=pattern.elements.findIndex(e=>e?.name===key);if(i<0)continue;
    const labelIndex=pattern.elements.findIndex(e=>['label','title','t'].includes(e?.name));
    for(const row of n.callee.object.elements)if(row?.type==='ArrayExpression'&&row.elements[i])add(row.elements[i],key==='hint'?'字段说明':'入口说明',null,context(n)+(labelIndex>=0?' → '+expr(row.elements[labelIndex]):''));
   }
  }
  if(n.type==='VariableDeclarator'&&n.id.name==='entries'&&path.basename(file)==='FeatureSearch.jsx'&&n.init?.type==='ArrayExpression')for(const row of n.init.elements)if(row.type==='ArrayExpression')add(row.elements[2],'入口说明',null,'功能查找 → '+expr(row.elements[0]));
 if(n.type==='JSXAttribute'){
   const key=n.name.name;if(['subtitle','hint','placeholder','description'].includes(key)&&n.value)add(n.value,{subtitle:'副标题',hint:'字段说明',placeholder:'输入框占位',description:'说明文字'}[key],null,context(n));
   if(key==='title'&&n.value&&hasText(n.value)&&expr(n.value).length>=18)add(n.value,'悬浮提示',null,context(n));
  }
  if(n.type==='ObjectProperty'&&['subtitle','hint','description','note'].includes(n.key.name||n.key.value))add(n.value,(n.key.name||n.key.value)==='subtitle'?'页面副标题':'配置说明',null,(raw(parents.get(n)).match(/(?:title|label|name):\s*['"]([^'"]+)/)||raw(parents.get(n)).match(/id:\s*['"]([^'"]+)/))?.[1]||context(n));
  if(n.type==='JSXElement'){
   const t=tag(n.openingElement.name),cl=attr(n,'className');const classText=cl?.type==='StringLiteral'?cl.value:'';
   let type=t==='Dialog.Description'?'弹窗说明':t==='Notice'||/notice/.test(classText)?'提示框':t==='p'||t==='small'||/push-hint|page-context|footnote|footer|empty|hint/.test(classText)?(/subtitle/.test(classText)?'副标题':/empty/.test(classText)?'空状态':t==='small'?'辅助文字':'说明文字'):null;
   if(type&&hasText(n))add(n,type,null,context(n));
  }
  for(const c of children(n))walk(c);
 }
 walk(ast);
 // Catch text embedded in configuration arrays, command explanations, conditions and feedback.
 function leftovers(n){
  if((['StringLiteral','JSXText'].includes(n.type)&&!claimed.has(n.start)&&/[\u3400-\u9fff]/.test(n.value))||(n.type==='TemplateLiteral'&&n.quasis.some(q=>!claimed.has(q.start)&&/[\u3400-\u9fff]/.test(q.value.cooked||'')))){
   const v=expr(n).trim();let p=n,chain=[];while(p&&chain.length<6){chain.push(p);p=parents.get(p)}
   const ca=chain.find(x=>x.type==='CallExpression'||x.type==='NewExpression'),call=ca?raw(ca.callee):'';
   let type=/notify|setError|setLoginError|Error|confirm|alert|action/.test(call)?'操作反馈与确认':'补充文案候选';
   if(['StringLiteral','JSXText'].includes(n.type)&&(v.length<10&&!/。|；|…|，|？/.test(v)))return;
   if(n.type==='JSXText'){type='行内说明候选';const p=parents.get(n);if(p?.type==='JSXElement'&&hasText(p)&&!['Button','button','a','Link','Dialog.Title','label','option','summary'].includes(tag(p.openingElement.name))){add(p,type,null,context(p));return;}}
   if(chain.some(x=>x.type==='ImportDeclaration'))return;
   add(n,type,v,context(n));
  }
  for(const c of children(n))leftovers(c)
 }
 leftovers(ast);
}
// Remove nested captures, retaining distinct attribute explanations.
entries=entries.filter((e,i,a)=>!a.some((x,j)=>j!==i&&x.file===e.file&&x.start<=e.start&&x.end>=e.end&&x.text.includes(e.text)&&x.type!=='补充文案候选'&&(x.start<e.start||j<i)));
entries.sort((a,b)=>a.file.localeCompare(b.file)||a.start-b.start);
const catalog=path.join(out,'inventory.json');
const previous=fs.existsSync(catalog)?JSON.parse(fs.readFileSync(catalog,'utf8')).entries:[];
const identity=e=>JSON.stringify([e.file,e.type,e.text]);
const known=new Map(previous.map(e=>[identity(e),e]));
let nextId=Math.max(0,...previous.map(e=>Number(e.id.slice(1))))+1;
for(const e of entries){const existing=known.get(identity(e));e.id=existing?.id||'T'+String(nextId++).padStart(3,'0');delete e.start;delete e.end;if(existing)Object.assign(existing,e);else previous.push(e)}
entries=previous;

fs.writeFileSync(path.join(out,'inventory.json'),JSON.stringify({generated:'2026-10-28',scope:'frontend/src 全部 JS/JSX 的界面文案。动态值以〔表达式〕表示；条件分支以 / 分隔。未包含真实聊天、日记或用户配置。',entries},null,2));
const esc=s=>s.replace(/\|/g,'\\|').replace(/\n/g,'<br>');let md='# 前端文案审阅清单\n\n日期：2026-10-28。只列清单，尚未按此清单删除产品文案。\n\n动态值以〔表达式〕表示；条件分支以 / 分隔。包含页面、面板、弹窗、字段、提示、空状态、占位及操作反馈；补充候选包含声明数组中的说明或较长标签。真实聊天与日记不在清单中。\n\n告诉我编号即可，例如：删除 T001、T012；T020 改成「……」。HTML 中的勾选只记录待删意见，不修改产品。\n\n';
for(const page of [...new Set(entries.map(e=>e.page))]){md+='## '+page+'\n\n| 编号 | 位置 | 类型 | 原文 | 源码 |\n|---|---|---|---|---|\n';for(const e of entries.filter(x=>x.page===page))md+=`| ${e.id} | ${esc(e.location)} | ${e.type} | ${esc(e.text)} | ${e.file}:${e.line}:${e.column} |\n`;md+='\n'}fs.writeFileSync(path.join(out,'INVENTORY.md'),md);
console.log(JSON.stringify({total:entries.length,types:entries.reduce((o,e)=>(o[e.type]=(o[e.type]||0)+1,o),{}),pages:entries.reduce((o,e)=>(o[e.page]=(o[e.page]||0)+1,o),{})},null,2));
