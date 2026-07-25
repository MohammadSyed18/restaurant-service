const money=cents=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100);
const cart=new Map();let menu=[],pending=null;
const status=document.querySelector('#status');
function render(){
 const query=document.querySelector('#search').value.toLowerCase();const container=document.querySelector('#menu');container.replaceChildren();
 for(const category of [...new Set(menu.map(item=>item.category))]){
  const group=document.createElement('details');group.open=true;const title=document.createElement('summary');title.textContent=category;group.append(title);
  for(const item of menu.filter(item=>item.category===category&&item.name.toLowerCase().includes(query))){
   const row=document.createElement('article');const name=document.createElement('h3');name.textContent=item.name;
   const price=document.createElement('p');price.textContent=money(item.price)+(item.allergens.length?' · Contains '+item.allergens.join(', '):'');
   const add=document.createElement('button');add.textContent='Add '+item.name;add.disabled=item.stock===0;add.onclick=()=>{cart.set(item.id,Math.min(item.stock,20,(cart.get(item.id)||0)+1));pending=null;renderCart()};row.append(name,price,add);group.append(row);
  }container.append(group);
 }
}
function renderCart(){const list=document.querySelector('#cart');list.replaceChildren();let total=0;for(const [id,quantity] of cart){const item=menu.find(item=>item.id===id);total+=item.price*quantity;const row=document.createElement('li');row.textContent=quantity+' × '+item.name+' ';const remove=document.createElement('button');remove.textContent='Remove';remove.onclick=()=>{cart.delete(id);pending=null;renderCart()};row.append(remove);list.append(row)}document.querySelector('#subtotal').textContent='Subtotal '+money(total)}
document.querySelector('#search').addEventListener('input',render);
document.querySelector('#pickup').addEventListener('change',()=>pending=null);
document.querySelector('#submit').onclick=async()=>{
 const button=document.querySelector('#submit');const pickup=document.querySelector('#pickup').value;
 if(!cart.size||!pickup){status.textContent='Add an item and choose a pickup time.';return}
 pending??=crypto.randomUUID();button.disabled=true;status.textContent='Sending your order…';
 try{const response=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':pending},body:JSON.stringify({items:[...cart].map(([id,quantity])=>({id,quantity})),pickup:new Date(pickup).toISOString()})});const result=await response.json();if(!response.ok)throw new Error(result.error);status.textContent='Order '+result.id.slice(0,8)+' accepted. Total '+money(result.total);cart.clear();pending=null;renderCart()}catch(error){status.textContent=error.message}finally{button.disabled=false}
};
try{const response=await fetch('/api/menu');if(!response.ok)throw new Error('Menu unavailable');menu=await response.json();render();renderCart()}catch(error){status.textContent=error.message}
