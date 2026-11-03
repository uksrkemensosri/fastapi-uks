(async () => {
  const container = document.getElementById('fasyankesDashboardContent');
  if (!container) return;
  const el = (tag, cls, text) => {const n=document.createElement(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const dateLabel = v => v ? new Intl.DateTimeFormat('id-ID',{day:'numeric',month:'short',year:'numeric'}).format(new Date(v+'T00:00:00')) : 'Belum dijadwalkan';
  try {
    const headers={Authorization:`Bearer ${localStorage.getItem('access_token')||''}`};
    const responses=await Promise.all(['/api/fasyankes','/api/fasyankes/schedule'].map(url=>fetch(url,{headers})));
    if(responses.some(r=>!r.ok))throw Error('Ringkasan belum tersedia. Coba muat ulang halaman.');
    const [cases,schedule]=await Promise.all(responses.map(r=>r.json()));
    const completed=cases.flatMap(c=>c.visits).filter(v=>v.actual_date&&v.status!=='DIBATALKAN').length;
    const metrics=el('div','faskes-metrics');
    for(const [count,label] of [[completed,'Kunjungan terlaksana'],[schedule.length,'Jadwal perlu dipantau']]){const m=el('div','faskes-metric');m.append(el('strong','',count),el('span','',label));metrics.append(m);}
    container.replaceChildren(metrics);
    if(!schedule.length){container.append(el('p','faskes-note','Belum ada jadwal kunjungan atau kontrol yang perlu ditindaklanjuti.'));return;}
    const sorted=[...schedule].sort((a,b)=>Number(Boolean(b.overdue))-Number(Boolean(a.overdue))||(a.date||'9999').localeCompare(b.date||'9999'));
    container.append(el('p','faskes-note','Prioritas tindak lanjut'));
    const list=el('ul','faskes-list');
    for(const item of sorted.slice(0,3)){
      const row=el('li',''),link=el('a','faskes-row'),top=el('div','faskes-row-top');
      link.href='/kolaborasi-fasyankes?case='+encodeURIComponent(item.case_id);
      top.append(el('span','faskes-name',item.patient_name),el('span','faskes-date'+(item.overdue?' overdue':''),dateLabel(item.date)));
      link.append(top,el('span','faskes-facility',`${item.kind||'Kunjungan'} · ${item.facility}${item.overdue?' · Jadwal terlewat':''}`));row.append(link);list.append(row);
    }
    container.append(list);
    if(schedule.length>3)container.append(el('p','faskes-note',`+${schedule.length-3} jadwal lainnya tersedia di daftar jadwal`));
  }catch(error){container.replaceChildren(el('p','faskes-note',error.message));}
})();
