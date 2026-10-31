(async () => {
  const container = document.getElementById('fasyankesDashboardContent');
  if (!container) return;
  try {
    const headers={Authorization:`Bearer ${localStorage.getItem('access_token')||''}`};
    const responses=await Promise.all(['/api/fasyankes','/api/fasyankes/schedule'].map(url=>fetch(url,{headers})));
    if(responses.some(r=>!r.ok))throw Error('Ringkasan belum tersedia');
    const [cases,schedule]=await Promise.all(responses.map(r=>r.json()));
    const visits=cases.flatMap(c=>c.visits);
    container.textContent='';
    const summary=document.createElement('p');
    summary.textContent=`${visits.filter(v=>v.actual_date&&v.status!=='DIBATALKAN').length} kunjungan terlaksana · ${schedule.length} jadwal / kontrol perlu dipantau`;
    container.append(summary);
    for(const item of schedule.slice(0,5)){
      const link=document.createElement('a');link.style.display='block';link.style.margin='10px 0';
      link.href='/kolaborasi-fasyankes?case='+item.case_id;
      link.textContent=`${item.patient_name} — ${item.facility} — ${item.date||'Menunggu jadwal'}${item.overdue?' (terlewat)':''}`;
      container.append(link);
    }
  }catch(error){container.textContent=error.message;}
})();
