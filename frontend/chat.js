const form=document.getElementById('chat-form');
const input=document.getElementById('message');
const messages=document.getElementById('messages');
const suggestions=document.getElementById('suggestions');
const usageLabel=document.getElementById('usage-label');
const modelLabel=document.getElementById('model-label');
let busy=false;
let sid=sessionStorage.getItem('mecky-session')||null;

function bubble(role,content,data={}){
  const box=document.createElement('div');box.className='bubble '+role;
  const body=document.createElement('div');body.className='bubble-text';body.textContent=content;box.append(body);
  const links=data.actions||data.links||[];
  if(links.length){const wrap=document.createElement('div');wrap.className='links';for(const link of links){if(!/^https:\/\//.test(link.url))continue;const a=document.createElement('a');a.href=link.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=(link.label||link.title||'Mehr erfahren')+' ↗';wrap.append(a)}box.append(wrap)}
  if(role==='mecky'&&data.show_feedback===true&&data.interaction_id){const fb=document.createElement('div');fb.className='feedback';for(const [rating,label] of [[1,'Hilfreich 👍'],[-1,'Nicht hilfreich 👎']]){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{await fetch('/feedback',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({interaction_id:data.interaction_id,rating})});fb.textContent='Danke für dein Feedback.'};fb.append(b)}box.append(fb)}
  messages.append(box);messages.scrollTop=messages.scrollHeight;return box;
}

function typing(){
  const box=bubble('mecky','');box.classList.add('typing-bubble');
  box.querySelector('.bubble-text').innerHTML='<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  document.getElementById('chat-status').textContent='Mecky schreibt …';return box;
}

function updateUsage(data){
  const u=data.session_usage;if(!u)return;
  const total=u.tokens_complete?u.tokens_total.toLocaleString('de-DE'):'unbekannt';
  const cost=u.cost_usd==null?'Kosten unbekannt':'$'+u.cost_usd.toFixed(4);
  usageLabel.textContent=total+' Tokens · '+cost;
  usageLabel.title=u.tokens_input+' Eingabe-Tokens, '+u.tokens_output+' Ausgabe-Tokens, '+u.model_calls+' Modellaufrufe in diesem Chat';
}

async function send(text){
  text=text.trim();if(!text||busy)return;busy=true;input.value='';suggestions.hidden=true;bubble('user',text);
  input.disabled=true;form.querySelector('button').disabled=true;const pending=typing();const started=performance.now();
  try{
    const r=await fetch('/chat/stream',{method:'POST',headers:{'content-type':'application/json','accept':'text/event-stream'},body:JSON.stringify({session_id:sid,message:text,client_context:{local_time:new Date().toISOString(),device_type:matchMedia('(max-width: 700px)').matches?'mobile':'desktop'}})});
    if(!r.ok||!r.body)throw new Error('Die Anfrage ist gerade nicht möglich.');
    const reader=r.body.getReader(),decoder=new TextDecoder();let buffer='',data=null,streamed='';
    pending.classList.remove('typing-bubble');pending.querySelector('.bubble-text').textContent='';
    while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});const blocks=buffer.split('\n\n');buffer=blocks.pop();for(const block of blocks){const kind=(block.match(/^event: (.+)$/m)||[])[1],raw=(block.match(/^data: (.+)$/m)||[])[1];if(!raw)continue;const event=JSON.parse(raw);if(kind==='meta')data=event;if(kind==='delta'){streamed+=event.text;pending.querySelector('.bubble-text').textContent=streamed;messages.scrollTop=messages.scrollHeight}}}
    if(!data)throw new Error('Ungültige Antwort');data.message=streamed;
    sid=data.session_id;sessionStorage.setItem('mecky-session',sid);updateUsage(data);
    if(data.usage?.model_called&&data.usage.model)modelLabel.textContent=data.usage.model;
    pending.remove();bubble('mecky',data.message,data);
  }catch(e){pending.remove();bubble('mecky','Die Verbindung hakt gerade. Versuch es bitte gleich noch einmal.')}
  finally{document.getElementById('chat-status').textContent='Online · Testchat';busy=false;input.disabled=false;form.querySelector('button').disabled=false;input.focus()}
}

form.addEventListener('submit',e=>{e.preventDefault();send(input.value)});
suggestions.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>send(b.textContent)));
document.getElementById('new-chat').addEventListener('click',()=>{
  if(busy)return;sid=null;sessionStorage.removeItem('mecky-session');messages.replaceChildren();
  bubble('mecky','Grüß Gott! Schön, dass du da bist. Wie kann ich dir bei deinem Besuch auf der Heuchelberger Warte helfen?');
  suggestions.hidden=false;usageLabel.textContent='0 Tokens · $0.0000';input.focus();
});
fetch('/model').then(r=>r.json()).then(data=>{modelLabel.textContent=data.model||'Regelmodus';usageLabel.textContent='0 Tokens · $0.0000'}).catch(()=>{modelLabel.textContent='Modellstatus unbekannt'});
