const staffEl = id => document.getElementById(id);
const staffStatus = msg => showStatus('visitStatus',msg,false);
let staffRequest = 0;

async function loadStaffHistory(){
  const target=staffEl('staffHistory'),id=staffEl('staffChoice').value,seq=++staffRequest;
  target.textContent=id?'Memuat riwayat…':'Pilih tendik untuk melihat riwayat.';
  if(!id)return;
  try{
    const visits=await api('/api/staff/'+id+'/visits','GET',null,true);
    if(seq!==staffRequest)return;
    target.replaceChildren();
    if(!visits.length)target.textContent='Belum ada kunjungan.';
    for(const v of visits){
      const row=document.createElement('details'),title=document.createElement('summary');
      title.textContent=v.visit_date+' · '+v.complaint;row.append(title);
      for(const [label,value] of [['Pemeriksaan',v.examination],['Diagnosis',v.diagnosis],['Tindakan',v.treatment],['Obat',(v.medications||[]).map(m=>m.medicine_name+' · '+m.dosage+' × '+m.quantity).join('; ')],['Anjuran',v.advice],['Catatan internal',v.notes]]){
        if(value){const p=document.createElement('p');p.textContent=label+': '+value;row.append(p);}
      }
      target.append(row);
    }
  }catch(err){if(seq===staffRequest)target.textContent=err.message;}
}

async function loadStaff(selected=''){
  const rows=await api('/api/staff','GET',null,true),select=staffEl('staffChoice');
  select.replaceChildren(new Option('Pilih tendik…',''));
  for(const s of rows)select.add(new Option(s.name+' · '+s.position+' (#'+s.id+')',s.id));
  select.value=String(selected);await loadStaffHistory();
}

async function switchPopulation(selected=''){
  const staff=staffEl('visitPopulation').value==='staff';
  editingVisitId=null;clearVisitForm();visitMedicines=[];renderMedicineList();
  staffEl('btnCreateVisit').textContent='Simpan Kunjungan';
  staffEl('staffVisitPanel').hidden=!staff;staffEl('studentVisitPicker').hidden=staff;
  staffEl('staffAdviceLabel').hidden=!staff;staffEl('staffAdvice').value='';
  staffEl('btnSuggestAI').hidden=staff;staffEl('visitStatus').textContent='';
  if(staff)await loadStaff(selected).catch(e=>staffStatus(e.message));
}
staffEl('visitPopulation').onchange=()=>switchPopulation();
staffEl('staffChoice').onchange=loadStaffHistory;
staffEl('staffRegister').onclick=async e=>{
  const button=e.currentTarget;button.disabled=true;
  try{
    const name=staffEl('staffName').value.trim(),position=staffEl('staffPosition').value.trim(),phone=staffEl('staffPhone').value.replace(/[\s()-]/g,'');
    if(!name||!position)throw Error('Isi nama dan jabatan tendik.');
    const body={name,position,phone};
    if(!staffEl('staffSchoolLabel').hidden){body.school_id=Number(staffEl('staffSchool').value);if(!body.school_id)throw Error('Pilih sekolah tendik.');}
    const s=await api('/api/staff','POST',body,true);
    for(const key of ['staffName','staffPosition','staffPhone'])staffEl(key).value='';
    staffEl('staffNew').open=false;await loadStaff(s.id);
    showStatus('visitStatus','Data tendik tersimpan. Lengkapi pemeriksaan untuk mencatat kunjungan.',true);
  }catch(err){staffStatus(err.message);}finally{button.disabled=false;}
};
(async()=>{
  const u=await staffViewer;if(!u)return;
  if(!['admin','perawat','super_admin'].includes(u.role))return;
  if(u.role==='super_admin'){
    const schools=await api('/api/schools','GET',null,true);
    staffEl('staffSchool').add(new Option('Pilih sekolah…',''));
    for(const s of schools)staffEl('staffSchool').add(new Option(s.school_name,s.id));
    staffEl('staffSchoolLabel').hidden=false;
  }
  staffEl('staffModeControl').hidden=false;
})().catch(e=>console.warn('Pilihan tendik tidak tersedia'));
