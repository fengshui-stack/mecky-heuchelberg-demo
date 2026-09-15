const form=document.getElementById('chat-form');
const input=document.getElementById('message');
const messages=document.getElementById('messages');
const suggestions=document.getElementById('suggestions');
let sid=sessionStorage.getItem('mecky-session')||null;
function bubble(role,text,links=[],id){
  const box=document.createElement('div');box.className='bubble '+role;
  if(role==='mecky'){const name=document.createElement('div');name.className='name';name.textContent='Mecky';box.append(name)}
  const p=document.createElement('div');p.textContent=text;box.append(p);
  if(links.length){const wrap=document.createElement('div');wrap.className='links';for(const link of links){if(!/^https:\/\//.test(link.url))continue;const a=document.createElement('a');a.href=link.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=(link.title||'Mehr erfahren')+' ↗';wrap.append(a)}box.append(wrap)}
  if(role==='mecky'&&id){const fb=document.createElement('div');fb.className='feedback';for(const [rating,label] of [[1,'Hilfreich 👍'],[-1,'Nicht hilfreich 👎']]){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{await fetch('/feedback',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({interaction_id:id,rating})});fb.replaceChildren(document.createTextNode('Danke für dein Feedback.'))};fb.append(b)}box.append(fb)}
  messages.append(box);messages.scrollTop=messages.scrollHeight;return box;
}
async function send(text){
  text=text.trim();if(!text)return;input.value='';suggestions.style.display='none';bubble('user',text);input.disabled=true;
  const pending=bubble('mecky','Mecky schaut nach …');
  try{const r=await fetch('/chat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({session_id:sid,message:text})});if(!r.ok)throw new Error('Die Anfrage ist gerade nicht möglich.');const data=await r.json();sid=data.session_id;sessionStorage.setItem('mecky-session',sid);pending.remove();bubble('mecky',data.message,data.links,data.interaction_id)}
  catch(e){pending.remove();bubble('mecky','Gerade klappt die Verbindung nicht. Versuch es bitte gleich noch einmal.')}finally{input.disabled=false;input.focus()}
}
form.addEventListener('submit',e=>{e.preventDefault();send(input.value)});
suggestions.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>send(b.textContent)));
