// Poker Preflop Trainer (static, no CSV)
// NOT solver GTO — “math-ish” baseline.
// Update: hide target mix until user answers; show breakdown after answer.

const CHART_RANKS = "AKQJT98765432";
const IDX = Object.fromEntries([...CHART_RANKS].map((r,i)=>[r,i]));
const POSITIONS = ["UTG","UTG1","LJ","HJ","CO","BTN","SB","BB"];
const POS_I = Object.fromEntries(POSITIONS.map((p,i)=>[p,i]));

const CHEN_BASE = {A:10,K:8,Q:7,J:6,T:5,"9":4.5,"8":4,"7":3.5,"6":3,"5":2.5,"4":2,"3":1.5,"2":1};

const $ = (id)=>document.getElementById(id);

function clamp01(x){ return Math.max(0, Math.min(1, x)); }
function normRCF(r,c,f){
  const s=r+c+f;
  if(s<=0) return [0,0,1];
  return [r/s,c/s,f/s];
}
function pct(x){ return `${Math.round(x*100)}%`; }
function pct1(x){ return `${(x*100).toFixed(1)}%`; } // 1 decimal

function cellHandLabel(rr, cc){
  if(rr===cc) return rr+cc;
  const ri=IDX[rr], ci=IDX[cc];
  if(ri<ci) return `${rr}${cc}s`;
  const hi = (IDX[cc] < IDX[rr]) ? cc : rr;
  const lo = (hi===cc) ? rr : cc;
  return `${hi}${lo}o`;
}

function parseHand(h){
  h = (h||"").trim().toUpperCase();
  if(h.length===2 && h[0]===h[1] && CHART_RANKS.includes(h[0])) return h;
  if(h.length===3 && CHART_RANKS.includes(h[0]) && CHART_RANKS.includes(h[1]) && (h[2]==="S"||h[2]==="O")){
    let a=h[0], b=h[1], t=h[2].toLowerCase();
    if(a===b) return a+a;
    // normalize hi/lo in chart order (A high -> lower index)
    if(IDX[a] > IDX[b]){ const tmp=a; a=b; b=tmp; }
    return `${a}${b}${t}`;
  }
  throw new Error("Bad hand");
}

function allSpots(){
  const spots=[];
  for(const p of POSITIONS){ if(p!=="BB") spots.push(`RFI_${p}`); }
  for(const opener of POSITIONS){
    if(opener==="BB") continue;
    for(const hero of POSITIONS){
      if(POS_I[hero] <= POS_I[opener]) continue;
      spots.push(`VS_${opener}_OPEN_${hero}`);
    }
  }
  for(const opener of POSITIONS){
    if(opener==="BB") continue;
    for(const tb of POSITIONS){
      if(POS_I[tb] <= POS_I[opener]) continue;
      spots.push(`RFI_${opener}_VS_3BET_${tb}`);
    }
  }
  return spots;
}

function spotType(spot){
  const s=spot.toUpperCase();
  if(s.startsWith("RFI_") && !s.includes("_VS_3BET_")) return "RFI";
  if(s.includes("_VS_3BET_")) return "VS3B";
  if(s.startsWith("VS_") && s.includes("_OPEN_")) return "VSOPEN";
  return "OTHER";
}
function spotActions(spot){
  const t=spotType(spot);
  if(t==="RFI") return ["RAISE","LIMP","FOLD"];
  if(t==="VSOPEN") return ["3BET","CALL","FOLD"];
  if(t==="VS3B") return ["4BET","CALL","FOLD"];
  return ["RAISE","CALL","FOLD"];
}
function parseSpotParts(spot){
  const s=spot.trim();
  if(s.startsWith("RFI_") && !s.includes("_VS_3BET_")) return ["RFI", s.split("_",2)[1], null];
  let m = /^VS_([A-Z0-9]+)_OPEN_([A-Z0-9]+)$/i.exec(s);
  if(m) return ["VSOPEN", m[1].toUpperCase(), m[2].toUpperCase()];
  m = /^RFI_([A-Z0-9]+)_VS_3BET_([A-Z0-9]+)$/i.exec(s);
  if(m) return ["VS3B", m[1].toUpperCase(), m[2].toUpperCase()];
  throw new Error("Bad spot");
}

// ----- config read -----
function cfg(){
  return {
    open: parseFloat($("openSize").value),
    threeIP: parseFloat($("threeIP").value),
    threeOOP: parseFloat($("threeOOP").value),
    rakePct: parseFloat($("rakePct").value)/100.0,
    rakeCap: parseFloat($("rakeCap").value),
    reqDisc: parseFloat($("reqDisc").value)/100.0,
    rIPo: parseFloat($("rIPo").value),
    rOOPo: parseFloat($("rOOPo").value),
    rIP3: parseFloat($("rIP3").value),
    rOOP3: parseFloat($("rOOP3").value),
    sbLimp: $("sbLimp").checked,
    rfiLoose: {
      UTG:0.05, UTG1:0.10, LJ:0.18, HJ:0.28, CO:0.45, BTN:0.62, SB:0.58
    }
  };
}

function rakeTaken(c, pot){
  return Math.min(pot*c.rakePct, c.rakeCap);
}

function chenScore(hand){
  if(hand.length===2){
    const r=hand[0];
    let score = CHEN_BASE[r]*2;
    if("AKQJT".includes(r)) score += 2;
    else if("987".includes(r)) score += 1;
    return Math.max(score, 5.0);
  }
  const hi=hand[0], lo=hand[1], t=hand[2];
  let base = Math.max(CHEN_BASE[hi], CHEN_BASE[lo]);
  if(t==="s") base += 2;
  const gap = Math.abs(IDX[lo]-IDX[hi]);
  if(gap===1) base += 1;
  else if(gap===2) base -= 1;
  else if(gap===3) base -= 2;
  else if(gap>=4) base -= 4;
  if(t==="s" && "98765".includes(hi) && gap<=2) base += 0.5;
  return Math.max(0.0, base);
}

function scoreToEquity(score){
  const x=(score-8.0)/4.5;
  const eq=0.45 + 0.18*(x/(1+Math.abs(x)));
  return clamp01(eq);
}

function blockers(hand){
  if(hand.length===2) return 0.2;
  const hi=hand[0], lo=hand[1];
  let w=0;
  if(hi==="A"||lo==="A") w+=1.0;
  if(hi==="K"||lo==="K") w+=0.6;
  if(hi==="Q"||lo==="Q") w+=0.3;
  return w;
}
function playability(hand){
  if(hand.length===2) return 0.6;
  const hi=hand[0], lo=hand[1], t=hand[2];
  const gap=Math.abs(IDX[lo]-IDX[hi]);
  let p=0;
  if(t==="s") p+=0.6;
  if(gap===1) p+=0.6;
  else if(gap===2) p+=0.35;
  else if(gap===3) p+=0.15;
  if("AKQJT".includes(hi) && "AKQJT".includes(lo)) p+=0.25;
  return p;
}

function reqEquityCall(c, call, potBefore){
  const potAfter = potBefore + call;
  let req = call / Math.max(1e-9, potAfter);
  req += rakeTaken(c, potAfter) / Math.max(1e-9, potAfter);
  req -= c.reqDisc;
  return clamp01(req);
}

function isIP(hero, villain){ return POS_I[hero] > POS_I[villain]; }

function target3bet(hero, opener){
  let base = ({UTG:0.03,UTG1:0.04,LJ:0.05,HJ:0.06,CO:0.08,BTN:0.11,SB:0.10,BB:0.07})[hero] ?? 0.06;
  base += 0.03*(POS_I[opener]/(POSITIONS.length-1));
  return clamp01(base);
}
function target4bet(opener, tb){
  let base=0.03;
  if((opener==="CO"||opener==="BTN") && (tb==="SB"||tb==="BB")) base+=0.01;
  return clamp01(base);
}

// ----- freqs -----
function freqsRFI(c, hand, pos){
  const score=chenScore(hand);
  const eq=scoreToEquity(score);
  const loose = c.rfiLoose[pos] ?? 0.0;
  const thr = 0.49 - 0.09*loose;
  let openFrac = clamp01((eq - (thr - 0.05))/0.10);
  if(openFrac<=0) return [0,0,1];

  let limp=0;
  if(pos==="SB" && c.sbLimp){
    const p=playability(hand), b=blockers(hand);
    let limpPref = clamp01(0.55*p - 0.25*b);
    limpPref *= clamp01(1.0 - 1.4*Math.max(0, eq-0.55));
    const limpShare = clamp01(0.55*limpPref);
    limp = openFrac*limpShare;
  }
  const raiseFrac = openFrac - limp;
  const fold = 1.0 - openFrac;
  return normRCF(raiseFrac, limp, fold);
}

function freqsVsOpen(c, hand, hero, opener){
  const eq=scoreToEquity(chenScore(hand));
  const ip=isIP(hero, opener);
  const pot0 = 1.5 + c.open;
  const callCost = c.open;
  const req = reqEquityCall(c, callCost, pot0);
  const realization = ip ? c.rIPo : c.rOOPo;
  const eqEff = clamp01(eq*realization);
  let callFrac = clamp01((eqEff - (req - 0.03))/0.08);

  const tgt = target3bet(hero, opener);
  const valueThr = ip ? 0.58 : 0.60;
  const value = clamp01((eq - (valueThr - 0.03))/0.06);

  const b=blockers(hand), p=playability(hand);
  const bluffSeed = clamp01(0.55*b + 0.15*p - 0.55*eq);
  const bluff = bluffSeed*0.35;

  const threeRaw = clamp01(0.75*value + 0.25*bluff);
  let threeFrac = clamp01(threeRaw*(tgt/0.10));

  let cont = callFrac + threeFrac;
  if(cont>1){
    const sc=1/cont;
    callFrac*=sc; threeFrac*=sc;
  }
  const fold = 1.0 - (callFrac + threeFrac);
  return normRCF(threeFrac, callFrac, fold);
}

function freqsVs3bet(c, hand, opener, tb){
  const eq=scoreToEquity(chenScore(hand));
  const ip=isIP(opener, tb);
  const size3 = ip ? c.threeIP : c.threeOOP;

  const pot0 = 1.5 + c.open + size3;
  const callCost = Math.max(0, size3 - c.open);
  const req = reqEquityCall(c, callCost, pot0);

  const realization = ip ? c.rIP3 : c.rOOP3;
  const eqEff = clamp01(eq*realization);
  let callFrac = clamp01((eqEff - (req - 0.03))/0.08);

  const tgt4 = target4bet(opener, tb);
  const value = clamp01((eq - (0.64 - 0.02))/0.05);

  const b=blockers(hand);
  const bluffSeed = clamp01(0.70*b - 0.85*eq + 0.10*playability(hand));
  const bluff = bluffSeed*(0.20 + ((tb==="SB"||tb==="BB")?0.08:0.0));

  const fourRaw = clamp01(0.85*value + 0.15*bluff);
  let fourFrac = clamp01(fourRaw*(tgt4/0.04));

  let cont = callFrac + fourFrac;
  if(cont>1){
    const sc=1/cont;
    callFrac*=sc; fourFrac*=sc;
  }
  const fold = 1.0 - (callFrac + fourFrac);
  return normRCF(fourFrac, callFrac, fold);
}

function freqsForSpot(c, spot, hand){
  const [t,a,b] = parseSpotParts(spot);
  if(t==="RFI") return freqsRFI(c, hand, a);
  if(t==="VSOPEN") return freqsVsOpen(c, hand, b, a);
  if(t==="VS3B") return freqsVs3bet(c, hand, a, b);
  return [0,0,1];
}

function sampleAction([r,c,f]){
  const x=Math.random();
  if(x<r) return "R";
  if(x<r+c) return "C";
  return "F";
}

// ----- state -----
let score=0, total=0;
let answered=false;

// ----- UI helpers -----
function clearAnswerUI(){
  answered=false;
  $("result").textContent="";
  $("result").className="result";
  $("mix").textContent=""; // hide
}

// ----- main panels -----
function setMode(){
  const m=$("mode").value;
  $("panelTitle").textContent = (m==="practice") ? "Practice" : "Chart";
  $("practicePanel").classList.toggle("hidden", m!=="practice");
  $("chartPanel").classList.toggle("hidden", m!=="chart");
  if(m==="chart") renderChart();
  else refreshPractice();
}

function refreshPractice(){
  const spot=$("spot").value;
  let hand=$("hand").value;
  try{ hand=parseHand(hand); $("hand").value=hand; }catch{}
  const c=cfg();
  const [r,cc,f]=freqsForSpot(c, spot, hand);
  const acts=spotActions(spot);

  $("prompt").textContent = `Spot: ${spot}   Hand: ${hand}   Choose: ${acts.join(" / ")}`;

  // IMPORTANT: hide mix until answered
  if(answered){
    $("mix").textContent = `Mix: ${acts[0]} ${pct(r)}   ${acts[1]} ${pct(cc)}   ${acts[2]} ${pct(f)}`;
  }else{
    $("mix").textContent = "";
  }

  $("a1").textContent=acts[0];
  $("a2").textContent=acts[1];
  $("a3").textContent=acts[2];
}

function answer(idx){
  const spot=$("spot").value;
  const c=cfg();
  const hand=parseHand($("hand").value);
  const freqs=freqsForSpot(c, spot, hand);
  const sampled=sampleAction(freqs);
  const acts=spotActions(spot);
  const chosen=["R","C","F"][idx];

  const [r,ca,f]=freqs;
  const chosenPct = (chosen==="R") ? r : (chosen==="C") ? ca : f;
  const sampledPct = (sampled==="R") ? r : (sampled==="C") ? ca : f;

  total += 1;
  const res=$("result");

  const breakdown =
    `Mix: ${acts[0]} ${pct1(r)} • ${acts[1]} ${pct1(ca)} • ${acts[2]} ${pct1(f)}\n` +
    `You chose: ${acts[["R","C","F"].indexOf(chosen)]} (${pct1(chosenPct)})\n` +
    `Sampled: ${acts[["R","C","F"].indexOf(sampled)]} (${pct1(sampledPct)})`;

  if(chosen===sampled){
    score += 1;
    res.textContent = `✅ Correct\n${breakdown}`;
    res.className = "result good";
  }else{
    res.textContent = `❌ Not this time\n${breakdown}`;
    res.className = "result bad";
  }

  $("score").textContent = `Score: ${score}/${total}`;

  answered=true;     // IMPORTANT: reveal mix after answering
  refreshPractice(); // re-render prompt + mix
}

function randomHand(){
  const hands=[];
  for(const r of CHART_RANKS) hands.push(r+r);
  for(let i=0;i<CHART_RANKS.length;i++){
    for(let j=i+1;j<CHART_RANKS.length;j++){
      const hi=CHART_RANKS[i], lo=CHART_RANKS[j];
      hands.push(`${hi}${lo}s`);
      hands.push(`${hi}${lo}o`);
    }
  }
  $("hand").value = hands[Math.floor(Math.random()*hands.length)];
  clearAnswerUI();
  refreshPractice();
}

function randomSpot(){
  const spots=allSpots();
  $("spot").value = spots[Math.floor(Math.random()*spots.length)];
  clearAnswerUI();
  setMode();
}

function nextQ(){
  const lock=$("lockSpot").checked;
  if(!lock) randomSpot();
  else{
    randomHand();
    return;
  }
  // randomSpot() already cleared + refreshed
}

function renderChart(){
  const spot=$("spot").value;
  const c=cfg();
  const cellMode=$("cellMode").value;
  const chart=$("chart");
  chart.innerHTML="";

  chart.appendChild(hdr(""));
  for(const r of CHART_RANKS) chart.appendChild(hdr(r));

  for(const rr of CHART_RANKS){
    chart.appendChild(hdr(rr));
    for(const cc of CHART_RANKS){
      const hand=cellHandLabel(rr, cc);
      const [r,ca,f]=freqsForSpot(c, spot, hand);
      const d=document.createElement("div");
      d.className="cell";

      let txt="";
      if(cellMode==="raise") txt = `${Math.round(r*100)}`;
      else if(cellMode==="call") txt = `${Math.round(ca*100)}`;
      else if(cellMode==="fold") txt = `${Math.round(f*100)}`;
      else txt = `${Math.round(r*100)}/${Math.round(ca*100)}/${Math.round(f*100)}`;

      d.textContent = txt;
      d.title = `${hand}  R:${pct(r)} C:${pct(ca)} F:${pct(f)} (click to set practice hand)`;

      d.addEventListener("click", ()=>{
        $("hand").value=hand;
        $("mode").value="practice";
        clearAnswerUI();
        setMode();
      });

      chart.appendChild(d);
    }
  }
}

function hdr(t){
  const d=document.createElement("div");
  d.className="hdr";
  d.textContent=t;
  return d;
}

// ----- init -----
function init(){
  const spots=allSpots();
  const spotSel=$("spot");
  spots.forEach(s=>{
    const o=document.createElement("option");
    o.value=s; o.textContent=s;
    spotSel.appendChild(o);
  });
  spotSel.value="RFI_BTN";

  $("mode").addEventListener("change", ()=>{ clearAnswerUI(); setMode(); });
  $("spot").addEventListener("change", ()=>{ clearAnswerUI(); setMode(); });
  $("hand").addEventListener("change", ()=>{ clearAnswerUI(); refreshPractice(); });

  $("randHand").addEventListener("click", randomHand);
  $("randSpot").addEventListener("click", randomSpot);
  $("nextQ").addEventListener("click", nextQ);

  $("a1").addEventListener("click", ()=>answer(0));
  $("a2").addEventListener("click", ()=>answer(1));
  $("a3").addEventListener("click", ()=>answer(2));

  $("cellMode").addEventListener("change", renderChart);

  // Any var change resets "answered" (so mix is hidden again)
  ["openSize","threeIP","threeOOP","rakePct","rakeCap","reqDisc","rIPo","rOOPo","rIP3","rOOP3","sbLimp"]
    .forEach(id=>$(id).addEventListener("input", ()=>{
      clearAnswerUI();
      if($("mode").value==="chart") renderChart();
      refreshPractice();
    }));

  clearAnswerUI();
  setMode();
  refreshPractice();
}
init();