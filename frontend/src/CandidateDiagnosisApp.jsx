import { useEffect, useRef, useState } from 'react';
import {
  Accordion, Alert, Badge, Button, Checkbox, Divider, FileButton, Grid,
  Group, Loader, Paper, ScrollArea, SimpleGrid, Stack, Text, Textarea,
  TextInput, Title,
} from '@mantine/core';
import { Dropzone } from '@mantine/dropzone';
import {
  IconArrowLeft, IconArrowRight, IconChartBar, IconCircleCheck,
  IconClipboardCheck, IconCloudUpload, IconDownload, IconFileText,
  IconInfoCircle, IconLock, IconPlus, IconRefresh, IconSettings,
  IconShieldCheck, IconSparkles, IconTargetArrow, IconTrash,
} from '@tabler/icons-react';
import { createClassicHandoff, saveClassicHandoff } from './resumeHandoff.js';
import { downloadTaskExport, draftDifferences, moduleRecomputePresentation, useCandidateWorkflow, workflowRequest } from './candidateWorkflow.js';

const STEPS = ['上传简历', '校对信息', '目标职位', '诊断报告', '优化清单'];
const SECTIONS = [
  ['match','任职资格匹配度'],
  ['experience','工作经验研判'],
  ['potential','学习能力与发展潜力'],
  ['motivation','简历针对性'],
  ['verification','简历疑点与风险提示'],
];
const JOBS = ['后端开发工程师', '前端开发工程师', 'Java 开发工程师', '数据分析师',
  '算法工程师', '机器学习工程师', '产品经理', 'UX 设计师', '测试工程师',
  '软件工程师', '项目经理', '运营专员'];
const ACCEPT = {
  'application/pdf': ['.pdf'],
  'application/msword': ['.doc'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'image/png': ['.png'],
  'image/jpeg': ['.jpg', '.jpeg'],
};
const KEYS = {
  name:'姓名',title:'当前职位 / 求职方向',email:'电子邮箱',phone:'电话',location:'所在城市',
  summary:'个人简介',self_evaluation:'自我评价',
};

const DEMO = [
  '陈晓明',
  '求职意向：后端开发工程师',
  '联系方式 demo@example.com',
  '个人简介',
  '拥有3年后端系统开发经验，熟悉 Python 与 SQL。',
  '专业技能',
  'Python, SQL, Docker, Git',
  '工作经历',
  '2022.07 - 2025.06 星辰科技 | 后端开发工程师',
  '- 参与订单系统后端开发，使用 Python 和 SQL。',
  '- 优化接口响应时间20%。',
  '项目经历',
  '订单服务系统',
  '- 开发 Python API，维护 Docker 部署。',
  '教育背景',
  '2018.09 - 2022.06 本科计算机科学',
  '证书',
  'CET-6',
].join('\n');

function lines(text) {
  return text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
}
function joinLines(values) { return (values || []).join('\n'); }
function fieldLabel(path) {
  const labels={...KEYS,experience:'工作经历',projects:'项目经历',education:'教育背景',company:'公司',role:'职位',start_date:'开始年月',end_date:'结束年月',heading:'标题',bullets:'职责与成果',details:'补充内容',skills:'技能',certificates:'证书',additional:'其他内容',target:'目标',requirements:'评分依据',weight:'权重',description:'要求说明',enabled:'是否纳入',hard_gate:'硬门槛',as_of:'统计时点',enabled_sections:'诊断范围',job_description:'岗位 JD'};
  return String(path||'').split('.').map(part=>/^\d+$/.test(part)?'第 '+(Number(part)+1)+' 项':labels[part]||part).join(' · ');
}
function displayValue(value) {
  if(Array.isArray(value))return value.map(item=>typeof item==='object'?Object.values(item).filter(v=>typeof v==='string').join(' · '):String(item)).join('；');
  return typeof value==='object'&&value?Object.values(value).filter(v=>typeof v==='string').join(' · '):String(value??'未填写');
}
function Status({ text, color = 'blue' }) { return <Badge color={color} radius="sm" variant="light">{text}</Badge>; }
function StepTitle({ code, title, children }) {
  return <div className="diag-step-heading">
    <div className="diag-eyebrow">{code} / PAPERPRO WORKSPACE</div>
    <Title order={2}>{title}</Title>
    <Text size="sm" c="dimmed" mt={7}>{children}</Text>
  </div>;
}
function Panel({ title, children, extra, testId }) {
  return <Paper className="diag-panel" p="xl" radius="lg" data-testid={testId}>
    <Group justify="space-between" align="center" mb="lg" wrap="wrap">
      <Title order={3} className="diag-panel-title">{title}</Title>
      {extra}
    </Group>
    {children}
  </Paper>;
}
function RecomputeSummary({ data, actual=false, onViewReport, onViewSource }) {
  if(!data)return null;
  const names=values=>(values||[]).map(key=>SECTIONS.find(([id])=>id===key)?.[1]||key).join('、')||'无';
  return <Panel title={actual?'本次检查的计算与复用':'本次变化与重算范围'} testId={actual?'candidate-recompute-result':'candidate-recompute-plan'}>
    {data.changed_fields?.length>0&&<Text size="sm" mb="md">变化字段：{data.changed_fields.map(path=>fieldLabel(path.replace(/^resume\./,''))).join('；')}</Text>}
    <div className="diag-recompute-grid">
      <div><Text fw={650} size="sm">{actual?'本次已计算':'需重新计算'}</Text><Text size="sm" data-testid="candidate-recompute-recomputed">{names(data.recomputed)}</Text></div>
      <div><Text fw={650} size="sm">{actual?'已复用结果':'可复用结果'}</Text><Text size="sm" data-testid="candidate-recompute-reused">{names(data.reused)}</Text></div>
      <div><Text fw={650} size="sm">本次关闭</Text><Text size="sm">{names(data.disabled)}</Text></div>
    </div>
    <Text size="xs" c="dimmed" mt="md">{actual?'复用保留原来的计算时点；本次只重新核对它是否仍适用于当前输入。':'未受影响的模块保留可读。按新快照完成检查后，再更新建议、待办依据和可导出的汇总报告。'}</Text>
    <Group gap="xs" mt="sm">
      {onViewReport&&<Button size="xs" variant="light" onClick={onViewReport} data-testid="candidate-recompute-view-report">查看保留的模块结果</Button>}
      {actual&&data.source_run_id&&onViewSource&&<Button size="xs" variant="subtle" onClick={()=>onViewSource(data.source_run_id)}>查看上次分析快照</Button>}
    </Group>
  </Panel>;
}
function Evidence({ refs, onLocate }) {
  if (!refs?.length) return <Text size="xs" c="dimmed">简历中未找到直接文字证据；不代表实际能力缺失。</Text>;
  return <div className="diag-evidence">
    {refs.map((ref, i) => <div key={i}>{onLocate?<button type="button" className="diag-evidence-link" onClick={()=>onLocate(ref.path)}>定位：{fieldLabel(ref.path)}</button>:<code>{fieldLabel(ref.path)}</code>}<span>{ref.original}</span></div>)}
  </div>;
}
function Match({ data, onLocate }) {
  return <>
    <div className="diag-score-intro">
      <div className="diag-score-ring" style={{ '--score': data.score || 0 }}>
        <span>{data.score}</span><small>/ 100</small>
      </div>
      <div className="diag-score-copy">
        <Group gap="xs" wrap="wrap"><Status text={'匹配等级 · ' + data.grade} color={data.grade === '高' ? 'teal' : data.grade === '中' ? 'blue' : 'orange'}/>
        <Status text={'置信说明 · ' + data.confidence} color="gray"/></Group>
        <Title order={3} mt="sm">{data.score_kind || '岗位证据覆盖度'}</Title>
        <Text size="sm" c="dimmed">{data.conclusion}</Text>
        <Text size="xs" mt={7}>{data.hr_interpretation}</Text>
        {data.job_fit_applicable===false&&<Text size="xs" c="orange" mt={4}>此数字不可与明确岗位的匹配分数横向比较。</Text>}
      </div>
    </div>
    <Alert variant="light" color="blue" icon={<IconInfoCircle size={17}/>} mb="md">
      {data.calibration_warning}
    </Alert>
    <div className="diag-table-wrap">
      <table className="diag-table" data-testid="requirements-table">
        <thead><tr><th>关键要求</th><th>匹配状态</th><th>系数</th><th>有效权重</th><th>加权贡献</th><th>原文证据</th></tr></thead>
        <tbody>{data.requirements.map(item => <tr key={item.id}>
          <td><strong>{item.label}</strong><Text size="xs" c="dimmed">{item.reason}</Text></td>
          <td><Status text={item.status} color={item.status === '已体现' ? 'teal' : item.status === '简历未体现' ? 'orange' : 'gray'}/></td>
          <td>{(item.coefficient * 100).toFixed(0)}%</td>
          <td>{(item.effective_weight * 100).toFixed(1)}%</td>
          <td>{Number(item.weighted_contribution??item.contribution??item.coefficient*item.effective_weight*100).toFixed(2)} 分</td>
          <td><Evidence refs={item.evidence_refs} onLocate={onLocate}/></td>
        </tr>)}</tbody>
      </table>
    </div>
  </>;
}
function Experience({ data }) {
  return <>
    <Group gap="sm" mb="md">
      <div className="diag-mini-stat"><strong>{data.stability_score == null ? '未知' : data.stability_score}</strong><small>稳定性参考分</small></div>
      <div className="diag-mini-stat"><strong>{data.months_total}</strong><small>已记录任职月数（去重）</small></div>
      <div className="diag-mini-stat"><strong>{data.gaps?.length || 0}</strong><small>需说明的空档</small></div>
    </Group>
    <Text size="sm">{data.career_continuity}</Text>
    <Text size="sm">{data.career_progression}</Text>
    <Divider my="md"/>
    <Text fw={700} size="sm" mb="xs">关键时间节点</Text>
    {(data.timeline || []).length ? data.timeline.map((node, i) => <div key={i} className="diag-timeline">
      <span>{node.start.slice(0, 7)} — {node.end.slice(0, 7)}</span>
      <div><strong>{node.company || '未填写公司'}</strong> · {node.role || '未填写职位'} <Text size="xs" c="dimmed">{node.months} 个月 · {node.path}</Text></div>
    </div>) : <Text size="sm" c="dimmed">没有可靠的起止年月，无法计算任期；请返回校对信息补齐。</Text>}
    <Text size="xs" c="dimmed" mt="md">{data.interpretation_boundary}</Text>
  </>;
}
function Potential({ data, onLocate }) {
  return <>
    <Group mb="md" gap="sm"><Status text={'证据信号评级 · ' + data.rating} color="indigo"/>
      <Text size="sm">{data.conclusion}</Text></Group>
    <div className="diag-signal-grid">{(data.signals || []).map((s, i) => <div className="diag-signal" key={i}>
      <Group justify="space-between"><strong>{s.signal}</strong><Status text={s.status} color={s.status === '支持' ? 'teal' : 'gray'}/></Group>
      {onLocate&&s.path?<Button size="xs" variant="subtle" onClick={()=>onLocate(s.path)}>定位：{fieldLabel(s.path)}</Button>:<Text size="xs" c="dimmed">{fieldLabel(s.path)}</Text>}
      <Text size="sm">{s.original || '简历未体现——请按实际情况补充'}</Text>
    </div>)}</div>
    {data.weakness&&<Alert color="blue" variant="light" mt="md" title={'可补强：' + data.weakness.signal}>{data.weakness.action}</Alert>}
    <Text size="xs" c="dimmed" mt="sm">{data.caveat}</Text>
  </>;
}
function Motivation({ data, onLocate }) {
  return <>
    <Group mb="md"><Status text={'定制程度 · ' + data.rating}/><Text size="sm">{data.conclusion}</Text></Group>
    <Text size="sm" mb="sm">{data.rationale}</Text>
    <Evidence refs={data.evidence} onLocate={onLocate}/>
    <Alert color="blue" mt="lg" variant="light" title="改进方向">{data.suggestion}</Alert>
  </>;
}
function Verification({ data, onLocate }) {
  return <>
    <Text size="sm" mb="md">{data.conclusion}</Text>
    {(data.issues || []).length ? data.issues.map((it, i) => <div className="diag-issue" key={it.id || i}>
      <Group mb="xs"><Status text={it.severity + ' · 需核对'} color={it.severity === '高' ? 'orange' : 'gray'}/><strong>{it.type}</strong></Group>
      <Text size="xs" c="dimmed">证据位置：{it.location}</Text>
      {onLocate&&it.location&&<Button size="xs" variant="subtle" onClick={()=>onLocate(it.location)}>定位原文与字段</Button>}
      <Text size="sm">{it.original}</Text>
      {it.related_location&&<Paper p="sm" withBorder radius="sm" mt="xs"
        data-testid="verification-opposing-claim">
        <Text size="xs" c="dimmed">另一处描述：{it.related_location}</Text>
        <Text size="sm">{it.related_original}</Text>
      </Paper>}
      <Text size="sm" mt={6}>{it.reason}</Text>
    </div>) : <Alert color="teal" variant="light">暂未发现规则能识别的存疑点；这不代表简历信息已经被外部核实。</Alert>}
    <Text size="xs" c="dimmed" mt="sm">{data.caveat}</Text>
  </>;
}
const REPORT_COMPONENTS = {match:Match, experience:Experience,potential:Potential,motivation:Motivation,verification:Verification};

function ResumeEditor({ resume, update, updateExperience, updateEntry, addEntry, removeEntry }) {
  return <Stack gap="lg">
    <Panel title="基本信息与自我评价">
      <SimpleGrid cols={{base:1,sm:2}} spacing="sm">
        {['name','title','email','phone','location'].map(field =>
          <TextInput key={field} label={KEYS[field]} value={resume[field] || ''}
            onChange={e => update(field,e.currentTarget.value)} data-testid={'candidate-'+field} data-field-path={field}/>)}
      </SimpleGrid>
      <Textarea mt="md" minRows={3} autosize label="个人简介"
        value={resume.summary || ''} onChange={e => update('summary',e.currentTarget.value)} data-field-path="summary"/>
      <Textarea mt="sm" minRows={2} autosize label="自我评价"
        value={resume.self_evaluation || ''} onChange={e => update('self_evaluation',e.currentTarget.value)} data-field-path="self_evaluation"/>
    </Panel>
    <Panel title="技能与证书">
      <Textarea label="技能（每行一项）" autosize minRows={2} value={joinLines(resume.skills)}
        onChange={e => update('skills',lines(e.currentTarget.value))} data-field-path="skills"/>
      <Textarea label="证书 / 资质（每行一项）" mt="md" autosize minRows={2}
        value={joinLines(resume.certificates)} onChange={e => update('certificates',lines(e.currentTarget.value))} data-field-path="certificates"/>
    </Panel>
    <Panel title="工作 / 实习经历" extra={<Button size="xs" variant="light" onClick={() => addEntry('experience')}
      leftSection={<IconPlus size={15}/>}>添加经历</Button>}>
      {(resume.experience || []).length === 0 && <Text size="sm" c="dimmed">尚无工作记录；可以添加实习经历，也可以留空。</Text>}
      {(resume.experience || []).map((entry, index) => <div className="diag-edit-entry" key={index}>
        <Group justify="space-between" mb="sm"><Text fw={700}>经历 {index+1}</Text>
          <Button size="xs" color="gray" variant="subtle" onClick={() => removeEntry('experience',index)} leftSection={<IconTrash size={13}/>}>删除</Button>
        </Group>
        <SimpleGrid cols={{base:1,sm:2}} spacing="sm">
          <TextInput label="公司 / 机构" value={entry.company||''} data-testid={'experience-company-'+index}
            onChange={e=>updateExperience(index,'company',e.currentTarget.value)} data-field-path={'experience.'+index+'.company'}/>
          <TextInput label="职位 / 职能" value={entry.role||''} data-testid={'experience-role-'+index}
            onChange={e=>updateExperience(index,'role',e.currentTarget.value)} data-field-path={'experience.'+index+'.role'}/>
          <TextInput label="开始年月" placeholder="2022.07" value={entry.start_date||''}
            data-testid={'experience-start-'+index} onChange={e=>updateExperience(index,'start_date',e.currentTarget.value)} data-field-path={'experience.'+index+'.start_date'}/>
          <TextInput label="结束年月" placeholder="2025.06 或 至今" value={entry.end_date||''}
            data-testid={'experience-end-'+index} onChange={e=>updateExperience(index,'end_date',e.currentTarget.value)} data-field-path={'experience.'+index+'.end_date'}/>
        </SimpleGrid>
        <TextInput label="原始经历标题（用于溯源）" mt="sm" value={entry.heading||''}
          onChange={e=>updateExperience(index,'heading',e.currentTarget.value)} data-field-path={'experience.'+index+'.heading'}/>
        <Textarea mt="sm" minRows={3} autosize label="具体职责与成果（每行一项）"
          value={joinLines(entry.bullets)} onChange={e=>updateExperience(index,'bullets',lines(e.currentTarget.value))} data-field-path={'experience.'+index+'.bullets'}/>
      </div>)}
    </Panel>
    <Panel title="项目与教育背景">
      {['projects','education'].map(group => <div key={group} className="diag-edit-group">
        <Group justify="space-between" mb="sm"><Text fw={700}>{group==='projects'?'项目经历':'教育背景'}</Text>
          <Button size="xs" variant="light" leftSection={<IconPlus size={14}/>}
            onClick={()=>addEntry(group)}>添加</Button></Group>
        {(resume[group]||[]).map((entry,i) => <div className="diag-edit-entry" key={i}>
          <Group justify="space-between" mb="xs"><Text size="xs">条目 {i+1}</Text>
            <Button size="xs" color="gray" variant="subtle" onClick={()=>removeEntry(group,i)}>删除</Button></Group>
          <TextInput label={group==='projects'?'项目标题':'学校、学历与时间'} value={entry.heading||''}
            onChange={e=>updateEntry(group,i,'heading',e.currentTarget.value)} data-field-path={group+'.'+i+'.heading'}/>
          <Textarea mt="sm" autosize minRows={2} label={group==='projects'?'项目动作/成果':'教育补充信息'}
            value={joinLines(entry[group==='projects'?'bullets':'details'])}
            onChange={e=>updateEntry(group,i,group==='projects'?'bullets':'details',lines(e.currentTarget.value))} data-field-path={group+'.'+i+'.'+(group==='projects'?'bullets':'details')}/>
        </div>)}
      </div>)}
    </Panel>
    <Panel title="其他未分类内容">
      <Textarea autosize minRows={2} value={joinLines(resume.additional)}
        onChange={e=>update('additional',lines(e.currentTarget.value))} data-field-path="additional"/>
    </Panel>
  </Stack>;
}

export default function CandidateDiagnosisApp() {
  const workflow = useCandidateWorkflow();
  const { task, draft, saveStatus, saveError, bindTask, updateDraft } = workflow;
  const [step,setStep]=useState(0);
  const [paste,setPaste]=useState('');
  const [privacyConsent,setPrivacyConsent]=useState(false);
  const [tasks,setTasks]=useState([]);
  const [tasksReady,setTasksReady]=useState(false);
  const [aiEnabled,setAiEnabled]=useState(false);
  const [aiConsent,setAiConsent]=useState(false);
  const [aiKey,setAiKey]=useState("");
  const [busy,setBusy]=useState('');
  const [elapsed,setElapsed]=useState(0);
  const [error,setError]=useState('');
  const [navNotice,setNavNotice]=useState('');
  const [requirementNotice,setRequirementNotice]=useState('');
  const [focusedField,setFocusedField]=useState('');
  const [pendingFieldsOnly,setPendingFieldsOnly]=useState(false);
  const [ignoredHints,setIgnoredHints]=useState([]);
  const [editTexts,setEditTexts]=useState({});
  const [adoptionErrors,setAdoptionErrors]=useState({});
  const [todoFilter,setTodoFilter]=useState('all');
  const [history,setHistory]=useState(null);
  const [historyView,setHistoryView]=useState(null);
  const [conflictVersion,setConflictVersion]=useState(null);
  const requestId=useRef(0);
  const activeOperation=useRef(null);
  const modificationInputs=useRef({});
  const resume=draft.resume;
  const target=draft.target;
  const enabled=draft.enabled_sections;
  const fileMeta=task?.source;
  const run=task?.current_run;
  const report=run?.report;
  const modifications=task?.modifications||{};
  const selected=Object.keys(modifications).filter(id=>['adopted','completed'].includes(modifications[id].status));
  const reviewHints=(fileMeta?.review_hints||[]).filter(h=>h.status==='unverified'&&!ignoredHints.includes(h.id));
  const quality=task?.quality||{blockers:[],warnings:[]};
  const validModules=SECTIONS.filter(([key])=>report?.dimensions?.[key]?.status==='ok');
  const selectedModules=enabled.length;
  const lockedRun=['cancelled','interrupted','running'].includes(run?.status)||(run?.status==='failed'&&!report);
  const stale=!!run?.stale||saveStatus!=='saved'||lockedRun;
  const resultsLocked=stale||run?.status==='failed';
  const readyTarget=!!target.role.trim()&&selectedModules>0;
  const requirements=draft.requirements||[];
  const totalWeight=requirements.filter(item=>item.enabled!==false).reduce((sum,item)=>sum+Number(item.weight||0),0);
  const weightsValid=requirements.some(item=>item.enabled!==false)&&requirements.filter(item=>item.enabled!==false).every(item=>
    Number.isFinite(Number(item.weight))&&Number(item.weight)>=0&&Number(item.weight)<=100&&String(item.label||'').trim())
    &&Math.abs(totalWeight-100)<0.000001;
  const readyRun=readyTarget&&draft.review_confirmed&&draft.requirements_confirmed
    &&weightsValid
    &&saveStatus!=='error'&&!(quality.blockers||[]).length&&!(quality.missing_confirmation||[]).length;
  const questionList=report?.interview_questions||[];
  const suggestions=report?.suggestions||[];
  const completed=selected.filter(id=>modifications[id].status==='completed').length;
  const unsavedModifications=suggestions.some(s=>editTexts[s.id]!==undefined&&editTexts[s.id]!==String(modifications[s.id]?.text||''));
  const fields=task?.field_records||[];
  const focusedRecord=fields.find(field=>field.path===focusedField)||fields.find(field=>field.path.startsWith(focusedField+'.'));
  const criticalFields=quality.critical_fields||[];
  const recomputePlan=run?.recompute;
  const executedRecompute=report?.meta?.recompute;

  async function refreshTasks() {
    try { const data=await workflowRequest('/api/diagnosis/tasks');setTasks(Array.isArray(data)?data:data.tasks||[]);setTasksReady(true); }
    catch(e) { setError(e.message); }
  }
  useEffect(()=>{if(step===0)refreshTasks();},[step]);
  useEffect(()=>{
    if(step===1&&focusedField)focusField(focusedField);
  },[step,focusedField]);

  useEffect(()=>{
    if(!busy){setElapsed(0);return undefined;}
    const began=Date.now();
    const timer=setInterval(()=>setElapsed(Math.floor((Date.now()-began)/1000)),1000);
    return ()=>clearInterval(timer);
  },[busy]);

  useEffect(()=>{
    if(!task?.id||!['parse','report'].includes(busy))return undefined;
    const token=requestId.current;
    const id=task.id;
    const timer=setInterval(async()=>{
      try {
        const data=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(id));
        if(token===requestId.current)workflow.observeTask(data);
      } catch { /* The main operation reports a failure; polling never invents success. */ }
    },1200);
    return ()=>clearInterval(timer);
  },[task?.id,busy]);

  function acceptTask(value,nextStep) {
    bindTask(value);
    setIgnoredHints([]);
    setEditTexts(Object.fromEntries(Object.entries(value.modifications||{}).map(([id,item])=>[id,item.text||''])));
    setAdoptionErrors({});
    setPendingFieldsOnly(false);
    if(nextStep!==undefined)setStep(nextStep);
  }

  async function flushDraft() {
    try { return await workflow.flush(); }
    catch(e) { setError('修改尚未保存：'+e.message);throw e; }
  }

  function invalidate() {
    // The inputs bind an in-flight diagnosis: changing any input revokes the
    // older response, including the case where report generation is pending.
    requestId.current += 1;
    setBusy(previous => ['report','requirements'].includes(previous) ? '' : previous);
    if(activeOperation.current) {
      const active=activeOperation.current;
      activeOperation.current=null;
      workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(active.taskId)+'/cancel',{
        method:'POST',json:{operation_id:active.id},
      }).then(value=>workflow.acceptUnchangedRevision(value)).catch(()=>{});
    }
    setNavNotice('信息已更新，相关结果待重新确认；原报告保留在历史记录中。');
  }
  function modify(field,value){
    updateDraft(previous=>({...previous,resume:{...previous.resume,[field]:value},review_confirmed:false})); invalidate();
  }
  function confirmField(path,checked) {
    updateDraft(previous=>{
      const values=new Set(previous.confirmed_fields||[]);
      if(checked)values.add(path);else values.delete(path);
      return {...previous,confirmed_fields:[...values],review_confirmed:criticalFields.every(field=>values.has(field.path))};
    });
  }
  function modifyEntry(group,index,field,value){
    updateDraft(previous=>({...previous,resume:{...previous.resume,
      [group]:previous.resume[group].map((e,i)=>i===index?{...e,[field]:value}:e)},review_confirmed:false}));
    if(group==='experience')setIgnoredHints(previous=>[...previous,...reviewHints.filter(h=>h.experience_index===index).map(h=>h.id)]);
    invalidate();
  }
  function addEntry(group){
    const next=group==='experience'
      ? {heading:'',company:'',role:'',start_date:'',end_date:'',bullets:[]}
      : group==='education' ? {heading:'',details:[]} : {heading:'',bullets:[]};
    updateDraft(previous=>({...previous,resume:{...previous.resume,[group]:[...(previous.resume[group]||[]),next]},review_confirmed:false}));invalidate();
  }
  function removeEntry(group,index){
    updateDraft(previous=>({...previous,resume:{...previous.resume,[group]:previous.resume[group].filter((_,i)=>i!==index)},review_confirmed:false}));
    if(group==='experience')setIgnoredHints(reviewHints.map(h=>h.id));
    invalidate();
  }
  function acceptWorkHint(hint){
    const index=hint.experience_index;
    const entry=resume?.experience?.[index];
    if(!entry || entry.role || entry.heading!==hint.source_heading
       || !entry.company.includes(hint.suggested_company)
       || !entry.company.includes(hint.suggested_role)){
      setIgnoredHints(previous=>[...previous,hint.id]);
      return;
    }
    updateDraft(previous=>({
      ...previous,review_confirmed:false,resume:{...previous.resume,
      experience:previous.resume.experience.map((item,i)=>i===index?{
        ...item,company:hint.suggested_company,role:hint.suggested_role
      }:item)}
    }));
    setIgnoredHints(previous=>[...previous,hint.id]);
    invalidate();
  }
  function modifyTarget(field,value){
    updateDraft(previous=>({...previous,target:{...previous.target,[field]:value},requirements:field==='company'?previous.requirements:[],requirements_confirmed:false}));invalidate();
  }
  function changePaste(value){
    // Typing a new source invalidates a pending parse of the earlier text.
    requestId.current += 1;
    setPaste(value);
    setBusy(previous=>previous==='parse'?'':previous);
    if(busy==='parse'&&activeOperation.current) {
      const active=activeOperation.current;
      activeOperation.current=null;
      workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(active.taskId)+'/cancel',{
        method:'POST',json:{operation_id:active.id},
      }).catch(()=>{});
    }
  }
  async function parseTask(value,token) {
    setAiEnabled(false);setAiConsent(false);setAiKey('');
    acceptTask(value,0);
    const operationId=crypto.randomUUID();
    activeOperation.current={id:operationId,taskId:value.id};
    const result=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(value.id)+'/parse',{
      method:'POST',json:{operation_id:operationId},
    });
    if(token!==requestId.current)return;
    activeOperation.current=null;
    acceptTask(result,result.state?.resume?1:0);
    setNavNotice('');
    refreshTasks();
  }
  async function importFile(file){
    if(!file||!privacyConsent||!tasksReady)return;
    const token=++requestId.current;
    setError('');
    if(file.size>10*1024*1024){setError('单文件上限 10 MB，请压缩后重新选择。');return;}
    const suffix=file.name.split('.').pop()?.toLowerCase();
    if(!['pdf','docx','doc','png','jpg','jpeg'].includes(suffix)){
      setError('仅支持 PDF、DOCX、DOC、PNG、JPG 或粘贴文本。');return;
    }
    const body=new FormData();body.append('file',file);body.append('privacy_consent','true');
    setBusy('parse');
    try{
      await flushDraft();
      const data=await workflowRequest('/api/diagnosis/tasks/upload',{method:'POST',body});
      if(token!==requestId.current)return;
      await parseTask(data,token);
    }catch(e){if(token===requestId.current)setError(e.message);}
    finally{if(token===requestId.current)setBusy('');}
  }
  async function importText(){
    if(!paste.trim()||!privacyConsent||!tasksReady)return;
    const token=++requestId.current;
    setBusy('parse');setError('');
    try{
      await flushDraft();
      const data=await workflowRequest('/api/diagnosis/tasks',{method:'POST',json:{text:paste,privacy_consent:true}});
      if(token!==requestId.current)return;
      await parseTask(data,token);
    }catch(e){if(token===requestId.current)setError(e.message);}
    finally{if(token===requestId.current)setBusy('');}
  }
  async function prepareRequirements() {
    if(!target.role.trim()||busy)return;
    const token=++requestId.current;
    setBusy('requirements');setError('');
    // Re-extraction revokes the previous confirmation immediately. Otherwise
    // an already-checked control can appear accepted while new items arrive.
    if(workflow.draftRef.current.requirements_confirmed) {
      updateDraft(previous=>({...previous,requirements_confirmed:false}));
    }
    try {
      await flushDraft();
      const result=await workflowRequest('/api/diagnosis/requirements',{method:'POST',json:{target}});
      if(token!==requestId.current)return;
      updateDraft(previous=>({...previous,requirements:result.requirements||[],requirements_confirmed:false}));
      setRequirementNotice([result.source==='user_jd'?'来源：用户提供的 JD':'来源：通用岗位模型（不代表目标公司的真实招聘要求）',...(result.warnings||[])].join('；'));
    }catch(e){if(token===requestId.current)setError(e.message);}
    finally{if(token===requestId.current)setBusy('');}
  }
  function changeRequirement(id,field,value) {
    updateDraft(previous=>({...previous,requirements:previous.requirements.map(item=>item.id===id?{...item,[field]:value}:item),requirements_confirmed:false}));
    invalidate();
  }
  function normalizeWeights() {
    const active=requirements.filter(item=>item.enabled!==false);
    if(!active.length)return;
    const sum=active.reduce((value,item)=>value+Number(item.weight||0),0);
    let used=0;
    const values=new Map(active.map((item,index)=>{
      const weight=index===active.length-1?Math.round((100-used)*100)/100:
        Math.round((sum?Number(item.weight||0)/sum:1/active.length)*10000)/100;
      used+=weight;return [item.id,weight];
    }));
    updateDraft(previous=>({...previous,requirements:previous.requirements.map(item=>values.has(item.id)?{...item,weight:values.get(item.id)}:item),requirements_confirmed:false}));
    invalidate();
  }
  async function generate(module) {
    if(!resume||busy||(!module&&!readyRun))return;
    const token=++requestId.current;
    setBusy('report');setError('');setNavNotice('');
    try{
      const current=await flushDraft();
      const operationId=crypto.randomUUID();
      activeOperation.current={id:operationId,taskId:current.id};
      const result=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(current.id)+(module?'/retry/'+module:'/run'),{method:'POST',json:{
        expected_revision:current.revision,operation_id:operationId,
        use_ai:aiEnabled,ai_consent:aiEnabled&&aiConsent,
        ai_provider:'deepseek',api_key:aiEnabled?aiKey:undefined,
      }});
      if(token!==requestId.current)return;
      activeOperation.current=null;
      acceptTask(result);
      updateDraft(previous=>({...previous,step:3}));
      setStep(3);
    }catch(e){if(token===requestId.current)setError(e.message);}
    finally{if(token===requestId.current)setBusy('');}
  }
  async function cancelOperation() {
    const previousAction=busy;
    const active=activeOperation.current||{taskId:task?.id,id:task?.active_operation};
    if(!active.taskId||!active.id)return;
    requestId.current+=1;
    setBusy('cancel');
    try {
      const value=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(active.taskId)+'/cancel',{
        method:'POST',json:{operation_id:active.id},
      });
      activeOperation.current=null;
      acceptTask(value);
      if(previousAction==='report'&&value.current_run?.report) {
        setStep(3);updateDraft(previous=>({...previous,step:3}));
      } else if(previousAction==='parse'&&value.state?.resume) {
        setStep(1);updateDraft(previous=>({...previous,step:1}));
      }
      setNavNotice('已取消未完成的处理，已完成结果和历史记录保留。');
    }catch(e){setError(e.message);}finally{setBusy('');}
  }
  async function exportSelected(kind,format,historicalRun) {
    if(!task||(!historicalRun&&(resultsLocked||unsavedModifications)))return;
    if(!historicalRun&&((kind==='todo'&&!selected.length)||(kind==='questions'&&!questionList.length)||(kind==='report'&&!validModules.length)))return;
    setBusy('export');setError('');
    try{
      await flushDraft();
      await downloadTaskExport(task.id,historicalRun||run.id,kind,format);
    }catch(e){setError(e.message);}
    finally{setBusy('');}
  }
  async function suggestionAction(suggestion,action) {
    const rawText=String(editTexts[suggestion.id]??modifications[suggestion.id]?.text??'');
    const text=rawText.trim();
    if(['adopt','complete'].includes(action)&&!text) {
      setAdoptionErrors(previous=>({...previous,[suggestion.id]:'请先填写实际修改内容，再采纳或完成。'}));
      modificationInputs.current[suggestion.id]?.focus();
      return;
    }
    if(resultsLocked||busy)return;
    setBusy('suggestion:'+suggestion.id);setError('');
    try {
      const current=await flushDraft();
      const value=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(current.id)+'/suggestions/'+encodeURIComponent(suggestion.id),{
        method:'PATCH',json:{expected_revision:current.revision,action,text},
      });
      bindTask(value);
      setEditTexts(previous=>(previous[suggestion.id]??modifications[suggestion.id]?.text??'')===rawText?
        {...previous,[suggestion.id]:value.modifications?.[suggestion.id]?.text??text}:previous);
      setAdoptionErrors(previous=>({...previous,[suggestion.id]:''}));
    }catch(e){setAdoptionErrors(previous=>({...previous,[suggestion.id]:'修改未保存：'+e.message}));}
    finally{setBusy('');}
  }
  async function loadTask(id) {
    setBusy('load');setError('');
    try {
      await flushDraft();
      requestId.current+=1;
      const value=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(id));
      const savedStep=value.state?.resume?Number(value.state?.step||1):0;
      acceptTask(value,savedStep>=3&&!value.current_run?.report?2:savedStep);
      setHistory(null);setHistoryView(null);setAiKey('');setAiConsent(false);setAiEnabled(false);
      setNavNotice(value.current_run?.stale?'已恢复任务；上游有修改，请重新确认相关结果。':'已恢复上次保存的任务。');
    }catch(e){setError(e.message);}finally{setBusy('');}
  }
  async function deleteTask(id) {
    if(busy)return;
    setBusy('delete');setError('');
    try {
      await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(id),{method:'DELETE'});
      if(task?.id===id) {
        requestId.current+=1;bindTask(null);setStep(0);setEditTexts({});setHistory(null);setHistoryView(null);
      }
      await refreshTasks();
      setNavNotice('任务、原始资料与历史记录已删除，不能继续访问或导出。');
    }catch(e){setError(e.message);}finally{setBusy('');}
  }
  async function showHistory(sourceRunId) {
    if(!task)return;
    try {
      await flushDraft();
      const value=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(task.id)+'/history');
      setHistory(value);
      const source=typeof sourceRunId==='string'?(value.runs||[]).find(item=>item.id===sourceRunId):null;
      setHistoryView(source?{kind:'run',value:source}:null);
      if(typeof sourceRunId==='string'&&!source)setNavNotice('来源记录可在历史版本中核对；当前未找到该报告的可读详情。');
    }catch(e){setError(e.message);}
  }
  async function inspectConflict() {
    try {
      const value=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(task.id));
      setConflictVersion(value);
    }catch(e){setError(e.message);}
  }
  async function confirmConflictSave() {
    if(!conflictVersion)return;
    const local=workflow.draftRef.current;
    setBusy('save');
    bindTask(conflictVersion);
    updateDraft(local);
    try{await flushDraft();setConflictVersion(null);setNavNotice('已按你确认的本页内容保存为新版本，服务器较早版本保留在历史中。');}
    catch { /* The local draft and conflict remain visible for another review. */ }
    finally{setBusy('');}
  }
  async function restoreVersion(versionId) {
    setBusy('restore');setError('');
    try {
      const current=await flushDraft();
      const value=await workflowRequest('/api/diagnosis/tasks/'+encodeURIComponent(current.id)+'/restore',{
        method:'POST',json:{expected_revision:current.revision,version_id:versionId},
      });
      requestId.current+=1;
      acceptTask(value,value.state?.resume?1:0);
      setAiEnabled(false);setAiConsent(false);setAiKey('');
      setHistory(null);setHistoryView(null);
      setNavNotice('历史内容已恢复为新的当前版本，请核对后重新诊断；后续历史仍然保留。');
    }catch(e){setError(e.message);}finally{setBusy('');}
  }
  function openClassicWithReviewedDraft(){
    if(!resume || !report || busy || resultsLocked || !draft.review_confirmed || unsavedModifications)return;
    try{
      const handoff=createClassicHandoff(resume,target,report,selected,{...fileMeta,name:fileMeta?.filename});
      // Only an explicit user click saves these local browser-tab facts.
      // It does not approve suggestions or enable any external AI provider.
      saveClassicHandoff(window.sessionStorage,handoff);
      window.location.assign('/classic');
    }catch(e){setError(e.message||'简历交接失败，请重新尝试。');}
  }
  function goTo(newStep){
    if(newStep>step)return;
    if(newStep===3&&!report)return;
    if(newStep===4&&!report)return;
    if(busy==='report' && newStep<step){
      requestId.current += 1;
      setBusy('');
    }
    navigate(newStep);
  }
  function navigate(newStep) {
    setError('');setStep(newStep);
    if(task)updateDraft(previous=>({...previous,step:newStep}));
  }
  function focusField(path) {
    setFocusedField(path);
    let candidate=String(path||'').replace(/\[(\d+)\]/g,'.$1');
    let input=null;
    while(candidate&&!input) {
      input=document.querySelector('[data-field-path="'+CSS.escape(candidate)+'"]');
      candidate=candidate.includes('.')?candidate.slice(0,candidate.lastIndexOf('.')):'';
    }
    input?.focus();input?.scrollIntoView({block:'center',behavior:'smooth'});
  }
  function locateEvidence(path) { navigate(1);setFocusedField(path); }

  return <div className="diag-root" data-testid="candidate-app">
    <aside className="diag-sidebar">
      <div className="diag-logo"><div className="diag-mark">P</div><div><strong>paper<span>pro</span></strong><small>INTELLIGENT CAREER</small></div></div>
      <div className="diag-side-kicker">工作台 / WORKSPACE</div>
      <div className="diag-side-current"><IconChartBar size={18}/><span>简历增强诊断</span></div>
      <a className="diag-side-link" href="/classic"><IconFileText size={18}/>经典简历编辑</a>
      <div className="diag-side-bottom"><IconShieldCheck size={17}/><span>本地优先 · 原件不改写<br/>建议由你自主采纳</span></div>
    </aside>

    <div className="diag-shell">
      <header className="diag-topbar">
        <div><span>职业竞争力分析</span><small> / 求职者端</small></div>
        <Group gap="xs"><Status text="R7–R10 Beta" color="indigo"/><a className="diag-top-link" href="/classic"><IconSettings size={16}/>经典设置</a></Group>
      </header>
      <main className="diag-content">
        <div className="diag-hero">
          <div><div className="diag-eyebrow">CANDIDATE INTELLIGENCE / PERSONAL REPORT</div>
          <Title order={1}>不仅优化表述，更要看懂<span>过筛逻辑。</span></Title>
          <Text c="dimmed" mt="sm">五大 HR 视角诊断，把岗位差距、履历节点与可能被追问的证据，变成可执行的优化待办。</Text></div>
          <div className="diag-hero-art"><div className="diag-art-score">86<small>/100</small><div>Evidence-based insight</div></div><span className="diag-art-node a"/><span className="diag-art-node b"/></div>
        </div>

        <div className="diag-progress" data-testid="wizard-steps">
          {STEPS.map((s,i)=><button key={s} type="button" className={'diag-progress-item '+(i===step?'is-active':i<step?'is-done':'')}
            disabled={!!busy||i>step||(i>=3&&!report)} onClick={()=>goTo(i)}>
            <span>{i<step?<IconCircleCheck size={17}/>:String(i+1).padStart(2,'0')}</span><strong>{s}</strong>
          </button>)}
        </div>
        {error&&<Alert mb="lg" color="red" withCloseButton onClose={()=>setError('')} title="操作未完成">{error}</Alert>}
        {navNotice&&<Alert mb="lg" color="orange" withCloseButton onClose={()=>setNavNotice('')}>{navNotice}</Alert>}
        {task&&<Paper p="md" className="diag-task-toolbar" mb="lg">
          <Group justify="space-between" gap="sm" wrap="wrap">
            <div><Text fw={700} size="sm">{fileMeta?.filename||'当前简历任务'} · 版本 {task.revision}</Text>
              <Text size="xs" c={saveStatus==='error'?'red':'dimmed'} data-testid="candidate-save-status">
                {saveStatus==='saved'?'已保存':saveStatus==='saving'?'保存中…':saveStatus==='error'?'未保存：'+saveError:'未保存，正在等待保存'}
              </Text>
            </div>
            <Group gap="xs">
              {saveStatus==='error'&&<Button size="xs" color="orange" onClick={()=>flushDraft().catch(()=>{})}>重试保存</Button>}
              {saveStatus==='error'&&<Button size="xs" variant="light" onClick={inspectConflict}>核对服务器版本</Button>}
              <Button size="xs" variant="light" onClick={showHistory} disabled={!!busy} data-testid="candidate-history">历史版本</Button>
              <Button size="xs" variant="subtle" color="red" disabled={!!busy} onClick={()=>deleteTask(task.id)}>删除任务及数据</Button>
            </Group>
          </Group>
          {saveStatus==='error'&&<Text size="xs" mt="xs">你的编辑仍保留在页面。请重试；若有版本冲突，请先复制需要保留的文字，再重新打开任务核对差异。</Text>}
        </Paper>}
        {run?.stale&&recomputePlan&&<RecomputeSummary data={recomputePlan} onViewReport={report&&step!==3?()=>navigate(3):undefined}/>}
        {conflictVersion&&<Panel title="保存冲突：核对版本差异" extra={<Button size="xs" variant="subtle" onClick={()=>setConflictVersion(null)}>暂不处理</Button>}>
          <Text size="sm" mb="md">本页编辑保留在左侧；服务器最新版本为 {conflictVersion.revision}。请核对后决定是否用本页内容创建新版本。历史记录不会被物理覆盖。</Text>
          {draftDifferences(draft,conflictVersion.state).map(item=><div className="diag-conflict-row" key={item.path}>
            <Text size="sm" fw={650}>{fieldLabel(item.path.replace(/^resume\./,''))}</Text>
            <Text size="sm">本页：{displayValue(item.local)}</Text><Text size="sm">服务器：{displayValue(item.server)}</Text>
          </div>)}
          <Button mt="md" color="orange" disabled={!!busy} onClick={confirmConflictSave}>确认以本页内容保存为新版本</Button>
        </Panel>}
        {history&&<Panel title="历史版本（只读）" testId="candidate-history-panel"
          extra={<Button size="xs" variant="subtle" onClick={()=>{setHistory(null);setHistoryView(null);}}>关闭历史</Button>}>
          <Text size="sm" c="dimmed" mb="md">查看历史不会改变当前内容；恢复会创建新版本，原有记录仍保留。</Text>
          <div className="diag-history-list">{(history.versions||[]).map(version=><div key={version.version_id}>
            <Text size="sm">版本 {version.revision} · {version.created_at} · {version.reason||'保存修改'}</Text>
            <Group gap="xs"><Button size="xs" variant="subtle" onClick={()=>setHistoryView({kind:'draft',value:version})}>查看此版本</Button>
              <Button size="xs" variant="light" disabled={!!busy} onClick={()=>restoreVersion(version.version_id)}>恢复为新版本</Button></Group>
          </div>)}</div>
          <Text fw={700} size="sm" mt="md">诊断记录</Text>
          {(history.runs||[]).map(item=><Group key={item.id} justify="space-between" className="diag-history-run">
            <Text size="sm">诊断 · 版本 {item.revision} · {item.report?.meta?.generated_at||item.created_at||''} · {item.stale?'历史结果':item.status}</Text>
            <Group gap="xs"><Button size="xs" variant="subtle" onClick={()=>setHistoryView({kind:'run',value:item})}>查看诊断</Button>
              <Button size="xs" variant="light" disabled={!!busy||!item.report||['cancelled','interrupted','running','failed'].includes(item.status)} onClick={()=>exportSelected('report','pdf',item.id)}>导出历史报告 PDF</Button></Group>
          </Group>)}
          {historyView?.kind==='draft'&&<Paper p="md" withBorder mt="md" radius="md">
            <Title order={4}>版本 {historyView.value.revision} · 只读履历</Title>
            <Text>{historyView.value.state?.resume?.name||'未填写姓名'} · {historyView.value.state?.resume?.title||''}</Text>
            <Text size="sm">目标：{historyView.value.state?.target?.role||'尚未设置'} / {historyView.value.state?.target?.company||'未指定公司'}</Text>
            <Text size="sm" mt="sm">{historyView.value.state?.resume?.summary||''}</Text>
            {(historyView.value.state?.resume?.experience||[]).map((entry,i)=><div key={i} className="diag-history-run">
              <Text size="sm" fw={600}>{entry.company} · {entry.role}</Text><Text size="xs">{entry.start_date} — {entry.end_date}</Text>
              {(entry.bullets||[]).map((line,j)=><Text key={j} size="sm">{line}</Text>)}
            </div>)}
          </Paper>}
          {historyView?.kind==='run'&&<div className="diag-history-detail">
            <Text fw={700} mt="md">历史诊断只读内容 · {historyView.value.snapshot?.target?.role||historyView.value.report?.target?.role}</Text>
            {SECTIONS.map(([key,label])=>{
              const data=historyView.value.report?.dimensions?.[key];const Component=REPORT_COMPONENTS[key];
              return <Paper key={key} p="md" withBorder mt="sm" radius="md"><Title order={4}>{label}</Title>
                {data?.status==='ok'?<Component data={data}/>:<Text size="sm">{data?.conclusion||'此模块未完成'}</Text>}
              </Paper>;
            })}
          </div>}
        </Panel>}
        {busy&&<Paper p="md" className="diag-loading" mb="lg">
          <Group gap="sm" justify="space-between"><Group gap="sm"><Loader size="sm"/><div><Text fw={700} size="sm">{busy==='parse'?'正在识别简历文字与结构':busy==='report'?'正在核算岗位要求与五维证据':busy==='requirements'?'正在整理岗位能力项':busy==='export'?'正在导出指定版本':busy.startsWith('suggestion:')?'正在保存修改状态':'正在处理任务'}</Text>
            <Text size="xs" c="dimmed">{elapsed} 秒 · {elapsed>=10?'已超过 10 秒，仍在处理；你可以继续等待或取消。':'按实际处理状态更新，原文件不会更改。'}</Text></div></Group>
            {['parse','report'].includes(busy)&&<Button size="xs" color="orange" variant="light" onClick={cancelOperation}>取消处理</Button>}
          </Group>
          {busy==='report'&&<Group mt="sm" gap="xs" wrap="wrap">{SECTIONS.map(([key,label])=>{
            const status=run?.module_status?.[key];
            const value=typeof status==='string'?status:status?.status;
            return <Status key={key} text={label+' · '+({ok:'已完成',completed:'已完成',running:'生成中',disabled:'已关闭',error:'失败',cancelled:'已取消'}[value]||'等待中')} color={value==='ok'?'teal':'gray'}/>;
          })}</Group>}
        </Paper>}

        {step===0&&<>
          <StepTitle code="01" title="上传简历，建立分析依据">支持文档、照片或粘贴文本。原件不改动；下一步由你核实解析内容。</StepTitle>
          {!tasksReady&&<Group mb="md"><Text size="sm" c="dimmed">正在加载保存的任务…</Text><Button size="xs" variant="subtle" onClick={refreshTasks}>重新加载</Button></Group>}
          {tasks.length>0&&<Panel title="继续上次任务">
            <div className="diag-task-list">{tasks.map(item=><div key={item.id}>
              <div><Text fw={650} size="sm">{item.filename||item.source?.filename||item.name||'简历任务'}</Text>
                <Text size="xs" c="dimmed">{item.role||item.target_role||item.target?.role||'尚未设置目标职位'} · 版本 {item.revision} · {item.updated_at}</Text></div>
              <Group gap="xs"><Button size="xs" variant="light" disabled={!!busy} onClick={()=>loadTask(item.id)}>继续任务</Button>
                <Button size="xs" variant="subtle" color="red" disabled={!!busy} onClick={()=>deleteTask(item.id)}>删除</Button></Group>
            </div>)}</div>
          </Panel>}
          <Alert color="blue" variant="light" mb="lg" title="简历数据使用与删除">
            简历仅用于你发起的解析、诊断、修改待办与导出，不默认用于模型训练。原文件保留为只读资料；请只提交本人或已获授权的资料。
            你可以继续保存的任务，或通过“删除任务及数据”删除原始资料、任务和历史。导出仅对当前浏览器拥有的任务开放。
            <Checkbox mt="sm" checked={privacyConsent} onChange={e=>setPrivacyConsent(e.currentTarget.checked)}
              label="我已了解数据用途，并同意处理本次提交的简历" data-testid="candidate-privacy-consent"/>
          </Alert>
          {task&&!resume&&<Paper p="md" mb="lg" withBorder radius="md"><Group justify="space-between">
            <Text size="sm">当前任务尚未完成解析，可使用原始资料重试。</Text>
            <Button size="xs" disabled={!!busy} onClick={async()=>{
              const token=++requestId.current;setBusy('parse');setError('');
              try{await parseTask(task,token);}catch(e){if(token===requestId.current)setError(e.message);}finally{if(token===requestId.current)setBusy('');}
            }}>重试解析原始资料</Button>
          </Group></Paper>}
          <div className="diag-upload-grid">
            <Panel title="导入文件" extra={<Status text="单文件 ≤10 MB" color="gray"/>}>
              <Dropzone accept={ACCEPT} maxFiles={1} maxSize={10*1024*1024} disabled={!!busy||!privacyConsent||!tasksReady}
                onDrop={files=>importFile(files[0])}
                onReject={()=>setError('文件无效：仅支持 PDF / Word / PNG / JPG，且不超过 10 MB。')}
                className="diag-dropzone" data-testid="candidate-dropzone">
                <IconCloudUpload size={40} stroke={1.5}/>
                <Text fw={750} mt="sm">拖拽简历或点击选择文件</Text>
                <Text c="dimmed" size="xs" mt={6}>PDF · DOCX · DOC · PNG · JPG</Text>
                <Text c="dimmed" size="xs" mt={3}>移动端可从相册或文件管理器选择</Text>
              </Dropzone>
              <Text c="dimmed" mt="md" size="xs">扫描文档会使用本地 OCR；复杂版式可能需要在下一步修正。</Text>
            </Panel>
            <Panel title="粘贴简历文本">
              <Textarea value={paste} onChange={e=>changePaste(e.currentTarget.value)}
                minRows={7} autosize placeholder="把简历全文粘贴在此，包含基本信息、教育、工作经历、技能等"
                data-testid="candidate-paste"/>
              <Group justify="space-between" mt="md">
                <Button variant="subtle" color="gray" size="sm" onClick={()=>changePaste(DEMO)}>填入虚构演示资料</Button>
                <Button onClick={importText} disabled={!paste.trim()||!!busy||!privacyConsent||!tasksReady}
                  rightSection={<IconArrowRight size={16}/>} data-testid="candidate-parse-text">解析文本</Button>
              </Group>
            </Panel>
          </div>
        </>}

        {step===1&&resume&&<>
          <StepTitle code="02" title="核对并修正履历信息">先确认公司、职位、任职起止时间与技术项目；后续评分只使用你确认后的结构化文本。</StepTitle>
          <Panel title="来源与解析说明" extra={<Status text={'已导入 · '+fileMeta?.method} color="teal"/>}>
            <Group gap="sm" wrap="wrap"><Text size="sm" fw={650}>{fileMeta?.filename}</Text>
              <Text size="xs" c="dimmed">原始 SHA-256：{fileMeta?.sha256?.slice(0,16)}…</Text></Group>
            {(fileMeta?.warnings||[]).map((w,i)=><Text size="xs" color="orange" key={i}>{w}</Text>)}
            <details className="diag-source"><summary>查看原始识别文本（核对依据）</summary>
              <Text size="xs" c="dimmed" my="xs">聚焦下方字段可查看对应原文；点击有字段关联的原文段落可返回该字段。原文始终只读。</Text>
              <div className="diag-source-paragraphs">{String(fileMeta?.text||resume.source_text||'').split(/\r?\n/).filter(Boolean).map((line,index)=>{
                const related=fields.find(field=>field.source_anchor?.excerpt&&field.source_anchor.excerpt.includes(line));
                const highlighted=focusedRecord?.source_anchor?.excerpt?.includes(line);
                return related?<button type="button" key={index} className={highlighted?'is-focused':''} onClick={()=>focusField(related.path)}>{line}</button>:
                  <div key={index}>{line}</div>;
              })}</div></details>
            {focusedField&&<Paper p="sm" mt="md" withBorder radius="md" data-testid="candidate-field-source">
              <Text fw={600} size="sm">{fieldLabel(focusedField)} · 原文对照</Text>
              {focusedRecord?.source_anchor?.excerpt?<Text size="sm" mt="xs"><mark>{focusedRecord.source_anchor.excerpt}</mark></Text>:
                <Text size="sm" c="dimmed">此内容没有可定位的原文锚点；如为本人新增，请核实事实后确认。</Text>}
              {focusedRecord?.edited_by_user&&<Text size="xs" c="orange" mt="xs">用户已修改：新内容不自动视为已被原文证明。原值：{displayValue(focusedRecord.original_value)}</Text>}
              {focusedRecord&&focusedRecord.anchor_status!=='valid'&&<Text size="xs" c="dimmed" mt="xs">已退化到可靠的段落摘录或待核对状态，不显示猜测的精确坐标。</Text>}
            </Paper>}
          </Panel>
          {reviewHints.length>0&&<Panel title="待确认的工作职位排版提示"
            testId="candidate-work-hints" extra={<Status text={reviewHints.length+' 项待核对'} color="orange"/>}>
            <Alert color="orange" variant="light" mb="md" icon={<IconInfoCircle size={17}/>}>
              同行的文字块不一定构成真实职位。以下均为未经核实的候选项，
              默认不写入简历、不进入评分。请对照原 PDF 确认后再采纳。
            </Alert>
            {reviewHints.map(h=><Paper key={h.id} p="md" mb="sm" withBorder radius="md"
              data-testid={'work-hint-'+h.id}>
              <Group gap="xs" wrap="wrap">
                <Status text="低置信度 · 未经校准" color="gray"/>
                <Status text="等待人工核实" color="orange"/>
              </Group>
              <Text size="xs" c="dimmed" mt={8}>
                原文位置：{h.source_path}
                {h.evidence?.page_number ? ' · PDF 第 '+h.evidence.page_number+' 页' : ''}
              </Text>
              {h.evidence?.boxes?.role&&<Text size="xs" c="dimmed">
                职位文字块定位：横向 {Math.round(h.evidence.boxes.role[0]*100)}%–{Math.round(h.evidence.boxes.role[2]*100)}%，
                纵向 {Math.round(h.evidence.boxes.role[1]*100)}%–{Math.round(h.evidence.boxes.role[3]*100)}%
              </Text>}
              <Text size="sm" mt={5}>原文：{h.source_heading}</Text>
              <Text size="sm" fw={600} mt={5}>候选机构：{h.suggested_company}</Text>
              <Text size="sm" fw={600}>候选职位：{h.suggested_role}</Text>
              <Text size="xs" c="dimmed">同行排版属于弱证据，未经过语义核查；不表示真实任职或评分概率。</Text>
              <Group mt="sm" gap="xs">
                <Button size="xs" onClick={()=>acceptWorkHint(h)}
                  data-testid={'accept-'+h.id}>已核对，采纳到表单</Button>
                <Button size="xs" variant="subtle" color="gray"
                  onClick={()=>setIgnoredHints(previous=>[...previous,h.id])}
                  data-testid={'ignore-'+h.id}>忽略此候选</Button>
              </Group>
            </Paper>)}
          </Panel>}
          <div onFocusCapture={event=>{if(event.target.dataset.fieldPath)setFocusedField(event.target.dataset.fieldPath);}}>
            <ResumeEditor resume={resume} update={modify} updateExperience={(i,f,v)=>modifyEntry('experience',i,f,v)}
              updateEntry={modifyEntry} addEntry={addEntry} removeEntry={removeEntry}/>
          </div>
          {fields.some(field=>field.edited_by_user)&&<Panel title="修改前后与来源标识">
            {fields.filter(field=>field.edited_by_user).map(field=><div key={field.path} className="diag-field-change">
              <Button size="xs" variant="subtle" onClick={()=>focusField(field.path)}>{fieldLabel(field.path)}</Button>
              <Text size="sm">原值：{displayValue(field.original_value)}</Text><Text size="sm">当前值：{displayValue(field.current_value)}</Text>
              <Text size="xs" c="dimmed">{field.value_origin==='user_added'?'用户新增，原文未提供':'用户已修改，请重新核对原文关系'}</Text>
            </div>)}
          </Panel>}
          <Panel title="质量检查与关键字段确认">
            {(quality.blockers||[]).map((item,i)=><Alert key={'block-'+i} color="red" mb="sm" title="需要先处理">
              {item.message} {item.path&&<Button size="xs" variant="subtle" onClick={()=>focusField(item.path)}>定位字段</Button>}
            </Alert>)}
            {(quality.warnings||[]).map((item,i)=><div key={'warning-'+i} className="diag-quality-warning">
              <Text size="sm">提醒：{item.message}</Text>{item.path&&<Button size="xs" variant="subtle" onClick={()=>focusField(item.path)}>核对字段</Button>}
            </div>)}
            {!(quality.blockers||[]).length&&<Text size="sm" c="dimmed" mb="md">当前未发现阻断项。日期缺失或不可靠的部分只展示限制，不强行计算年限。</Text>}
            {criticalFields.length>0&&<>
              <Group justify="space-between" mb="md" gap="sm" wrap="wrap">
                <Text size="sm">已确认 {(draft.confirmed_fields||[]).filter(path=>criticalFields.some(field=>field.path===path)).length} / {criticalFields.length} 个关键字段</Text>
                <Checkbox label="只看待核对" checked={pendingFieldsOnly} onChange={e=>setPendingFieldsOnly(e.currentTarget.checked)}/>
              </Group>
              <div data-testid="candidate-critical-fields">
                {criticalFields.filter(field=>!pendingFieldsOnly||!(draft.confirmed_fields||[]).includes(field.path)).map(field=><Paper key={field.path} p="sm" withBorder radius="md" mb="sm">
                  <Group justify="space-between" gap="sm" wrap="wrap">
                    <Checkbox checked={(draft.confirmed_fields||[]).includes(field.path)} disabled={saveStatus!=='saved'||!!(quality.blockers||[]).length}
                      label={'确认 '+fieldLabel(field.path)} data-testid={'confirm-field-'+field.path}
                      onChange={e=>confirmField(field.path,e.currentTarget.checked)}/>
                    <Button size="xs" variant="subtle" onClick={()=>focusField(field.path)}>对照原文</Button>
                  </Group>
                  <Text size="sm" mt={5}>{displayValue(field.current_value)}</Text>
                </Paper>)}
                {pendingFieldsOnly&&criticalFields.every(field=>(draft.confirmed_fields||[]).includes(field.path))&&<Text size="sm" c="teal" mb="md">关键字段均已确认。</Text>}
              </div>
            </>}
            <Checkbox checked={!!draft.review_confirmed} disabled={!!(quality.blockers||[]).length||saveStatus!=='saved'}
              onChange={e=>{const checked=e.currentTarget.checked;updateDraft(previous=>({...previous,review_confirmed:checked,confirmed_fields:checked?criticalFields.map(field=>field.path):[]}));}}
              label="我已对照原文核对关键时间、公司与职位；新增或修改内容符合事实" data-testid="candidate-review-confirmed"/>
            <Text size="xs" c="dimmed" mt="xs">此项是对当前关键字段的明确批量确认，也可以在上方逐项核对。修改字段后，只需重新确认受影响项。</Text>
          </Panel>
          <Group justify="space-between" mt="xl">
            <Button variant="subtle" leftSection={<IconArrowLeft size={16}/>} onClick={()=>navigate(0)}>返回更换文件</Button>
            <Button rightSection={<IconArrowRight size={16}/>} disabled={!draft.review_confirmed||!!(quality.blockers||[]).length||!!(quality.missing_confirmation||[]).length||saveStatus==='error'||!!busy}
              onClick={()=>navigate(2)} data-testid="candidate-next-target">下一步 · 设置目标</Button>
          </Group>
        </>}

        {step===2&&resume&&<>
          <StepTitle code="03" title="确认目标职位与评分依据">目标职位必填，公司与 JD 可选。请核对能力项、权重和分析范围，确认后再启动诊断。</StepTitle>
          <Panel title="岗位定位">
            <SimpleGrid cols={{base:1,sm:2}}>
              <TextInput label="目标职位" required placeholder="例如：后端开发工程师" value={target.role}
                onChange={e=>modifyTarget('role',e.currentTarget.value)}
                list="paperpro-job-suggestions" data-testid="candidate-target-role"/>
              <TextInput label="目标公司" placeholder="例如：示例科技有限公司" value={target.company}
                onChange={e=>modifyTarget('company',e.currentTarget.value)} data-testid="candidate-target-company"/>
            </SimpleGrid>
            <datalist id="paperpro-job-suggestions">{JOBS.map(item=><option value={item} key={item}/>)}</datalist>
            <Textarea mt="lg" minRows={6} autosize label="目标岗位 JD（可选，但推荐）"
              placeholder="请粘贴真实 JD：职责、任职条件、技术栈、工作年限等。我们不会根据公司名称虚构官方要求。"
              value={target.job_description} onChange={e=>modifyTarget('job_description',e.currentTarget.value)}/>
            {!target.role.trim()&&<Text size="xs" c="orange" mt="xs">请填写目标职位；仅填写公司不能开始诊断。</Text>}
            <Button mt="md" variant="light" disabled={!target.role.trim()||!!busy||saveStatus==='error'} onClick={prepareRequirements}
              data-testid="candidate-prepare-requirements">{requirements.length?'重新提取岗位能力项':'整理岗位能力项与权重'}</Button>
          </Panel>
          {requirements.length>0&&<Panel title="核对能力项与评分权重" testId="candidate-requirements"
            extra={<Status text={'已纳入权重 '+Number(totalWeight.toFixed(4))+'%'} color={weightsValid?'teal':'orange'}/>}>
            <Alert mb="md" color="blue" variant="light">{requirementNotice||
              (target.job_description.trim()?'来源：用户提供的 JD。请核对提取是否准确。':'来源：通用岗位模型（不代表目标公司的真实招聘要求）。')}</Alert>
            <div className="diag-requirements-editor">{requirements.map((item,index)=><Paper key={item.id} p="md" withBorder radius="md">
              <Group justify="space-between" mb="sm" gap="sm" wrap="wrap">
                <Checkbox checked={item.enabled!==false} label={'纳入评分 · 能力项 '+(index+1)}
                  onChange={e=>changeRequirement(item.id,'enabled',e.currentTarget.checked)}/>
                <Status text={item.source==='user_jd'?'用户 JD':'通用模型'} color="gray"/>
              </Group>
              <SimpleGrid cols={{base:1,sm:2}} spacing="sm">
                <TextInput label={'能力项 '+(index+1)+' 名称'} value={item.label||''} onChange={e=>changeRequirement(item.id,'label',e.currentTarget.value)}/>
                <TextInput type="number" min="0" max="100" step="0.01" label={'能力项 '+(index+1)+' 权重（%）'} value={item.weight??0}
                  error={Number(item.weight)<0||Number(item.weight)>100?'权重须在 0–100 之间':undefined}
                  onChange={e=>changeRequirement(item.id,'weight',e.currentTarget.value===''?0:Number(e.currentTarget.value))}/>
              </SimpleGrid>
              <Textarea mt="sm" autosize minRows={2} label={'能力项 '+(index+1)+' 要求描述'} value={item.description||''}
                onChange={e=>changeRequirement(item.id,'description',e.currentTarget.value)}/>
              <Checkbox mt="sm" checked={!!item.hard_gate} label="作为硬门槛核对" onChange={e=>changeRequirement(item.id,'hard_gate',e.currentTarget.checked)}/>
            </Paper>)}</div>
            <Group mt="md" mb="md" justify="space-between">
              <Text size="sm" c={weightsValid?'dimmed':'orange'}>纳入项须有名称，权重在 0–100 之间且合计 100%，评分使用与页面一致的权重。</Text>
              <Button size="xs" variant="subtle" onClick={normalizeWeights}>按比例归一到 100%</Button>
            </Group>
            <Checkbox checked={!!draft.requirements_confirmed} disabled={!!busy||saveStatus!=='saved'||!weightsValid}
              onChange={e=>updateDraft(previous=>({...previous,requirements_confirmed:e.currentTarget.checked}))}
              label="我已确认能力项、要求描述及权重，作为本次评分依据" data-testid="candidate-requirements-confirmed"/>
          </Panel>}
          <Panel title="HR 视角诊断维度" extra={<Status text="可独立关闭" color="gray"/>}>
            <SimpleGrid cols={{base:1,sm:2}} spacing="lg">
              {SECTIONS.map(([id,name])=><Checkbox key={id} label={name} checked={enabled.includes(id)}
                onChange={e=>{
                  const checked=e.currentTarget.checked;
                  updateDraft(previous=>({...previous,enabled_sections:checked?[...new Set([...previous.enabled_sections,id])]:previous.enabled_sections.filter(x=>x!==id)}));
                  invalidate();
                }}/>)}
            </SimpleGrid>
            {!enabled.length&&<Text size="sm" c="orange" mt="md">请至少开启一个诊断模块，不能生成空报告。</Text>}
            <TextInput mt="lg" type="date" label="统计时点（时间指标口径）" value={draft.as_of||''}
              onChange={e=>{updateDraft(previous=>({...previous,as_of:e.currentTarget.value}));invalidate();}}/>
            <Alert variant="light" color="blue" mt="lg" icon={<IconInfoCircle size={17}/>}>
              匹配度是“简历证据覆盖度”，不是 HR 录取概率。心理测量与经济学多准则权重尚需真实标注样本检验；本报告会明确展示规则版本。
            </Alert>
          </Panel>
          <Panel title="可选：DeepSeek 解读职业路径" extra={<Status text="默认关闭，不外发"/>}>
            <Checkbox checked={aiEnabled} label="使用 DeepSeek 为已计算的时间线与证据提供辅助解释（不允许重新打分）"
              onChange={e=>setAiEnabled(e.currentTarget.checked)}/>
            {aiEnabled&&<Stack gap="sm" mt="md">
              <TextInput type="password" autoComplete="off" label="DeepSeek API Key（可留空读取 settings.local.json）"
                value={aiKey} onChange={e=>setAiKey(e.currentTarget.value)}
                data-testid="candidate-ai-key"/>
              <Checkbox checked={aiConsent} onChange={e=>setAiConsent(e.currentTarget.checked)}
                label="我明确同意将相关经历、目标岗位和诊断证据发送给 DeepSeek 进行辅助解读"
                data-testid="candidate-ai-consent"/>
              <Text size="xs" c="dimmed">默认只运行本地规则。外部解读即使失败，也不影响五维确定性评分；定性内容仍需本人核实。</Text>
            </Stack>}
          </Panel>
          <Group justify="space-between" mt="xl">
            <Button variant="subtle" leftSection={<IconArrowLeft size={16}/>} onClick={()=>navigate(1)}>返回修改简历</Button>
            <Button onClick={()=>generate()} disabled={!readyRun||!!busy||(aiEnabled&&!aiConsent)}
              rightSection={<IconSparkles size={17}/>} data-testid="candidate-generate">
              {report?'重新检查受影响模块':'生成五维诊断报告'}
            </Button>
          </Group>
        </>}

        {step===3&&report&&<>
          <StepTitle code="04" title="HR 视角诊断报告">依据校对后的文本分析。每个结论都保留依据位置；不掌握的资料会明确标为“未体现”，不会被视为事实证明。</StepTitle>
          <div className="diag-report-meta"><div><strong>岗位：{report.target?.role||'未提供'} </strong> / 公司：{report.target?.company||'未提供'}</div>
            <div>生成时间 {report.meta.generated_at} · 规则版本 {report.meta.rules_version}</div></div>
          {!run.stale&&executedRecompute&&<RecomputeSummary data={executedRecompute} actual onViewSource={showHistory}/>}
          <Alert mb="lg" color={stale?'orange':validModules.length===enabled.length?'teal':'orange'} variant="light" data-testid="candidate-report-scope"
            title={lockedRun?'本次处理只读保留':stale?'待重新确认的历史结果':!validModules.length?'诊断未完成 · 暂无有效模块':validModules.length===enabled.length?'完整诊断报告':'部分诊断报告'}>
            已完成 {validModules.length} 项 · 已关闭 {SECTIONS.filter(([key])=>report.dimensions?.[key]?.status==='disabled').length} 项 ·
            失败或未完成 {SECTIONS.filter(([key])=>!['ok','disabled'].includes(report.dimensions?.[key]?.status)).length} 项。
            {lockedRun?' 本次处理已取消、中断或仍在生成。已完成内容保留供查看，未完成报告不能修改建议或导出；可返回目标页重新发起诊断。':
              stale?' 当前输入有变更或尚未保存；此处保留旧结果供核对，完成重新确认与诊断后才能继续操作。':
              validModules.length<enabled.length?' 建议只覆盖已完成且有效的模块，未覆盖范围请勿视为已检查。':' 以下结论均属于同一次确认的分析快照。'}
          </Alert>
          {report.meta.ai_narrative&&<Alert mb="lg" color={report.meta.ai_narrative==='completed'?'teal':'orange'} variant="light">
            {report.meta.ai_notice}
          </Alert>}
          {SECTIONS.map(([key,label],i)=>{
            const data=report.dimensions?.[key];
            const Component=REPORT_COMPONENTS[key];
            const presentation=moduleRecomputePresentation(key,{status:data?.status,stale:!!run.stale,plan:recomputePlan,actual:executedRecompute,affected:run.affected_modules||[]});
            const provenance=report.meta.module_provenance?.[key];
            const sourceId=provenance?.origin_run_id||provenance?.source_run_id||executedRecompute?.source_run_id;
            const reusable=run.stale&&recomputePlan?.reused?.includes(key);
            return <Panel key={key} testId={'dimension-'+key}
              title={<Group gap="xs" align="center"><span className="diag-section-index">{String(i+1).padStart(2,'0')}</span>{label}</Group>}
              extra={<Group gap="xs"><Status text={presentation.text} color={presentation.color}/>
                {!['ok','disabled'].includes(data?.status)&&<Button size="xs" variant="light" disabled={!!busy||stale} onClick={()=>generate(key)}>重试此模块</Button>}
              </Group>}>
              {data?.status==='ok'?<><Component data={data} onLocate={!stale||(reusable&&saveStatus==='saved'&&!lockedRun)?locateEvidence:undefined}/>{data.ai_commentary&&<Alert mt="lg" color="blue" variant="light" title="DeepSeek 辅助解读（仍需核实）">{data.ai_commentary}</Alert>}</>:<Text size="sm" c="dimmed">{data?.conclusion||'暂无结果'}</Text>}
              {provenance&&data?.status==='ok'&&<div className="diag-module-origin">
                <Text size="xs" c="dimmed">{provenance.computed_as_of?'原计算时点：'+provenance.computed_as_of:''}
                  {provenance.validated_as_of?' · 已核对时点：'+provenance.validated_as_of:''}</Text>
                {sourceId&&((!run.stale&&sourceId!==run.id)||reusable)&&<Button size="xs" variant="subtle" onClick={()=>showHistory(sourceId)}>查看结果来源</Button>}
              </div>}
            </Panel>;
          })}
          <Panel title="面试准备清单预览" extra={<Status text={questionList.length+' 条'} color="gray"/>}>
            {questionList.length ? questionList.slice(0,4).map(q=><div className="diag-question" key={q.id}>
              <strong>{q.check}</strong><Text size="sm">{q.question}</Text><Text size="xs" c="dimmed">{q.purpose}</Text>
            </div>):<Text size="sm" c="dimmed">未识别到需要生成核查问题的高/中风险存疑点。</Text>}
          </Panel>
          <Alert color="orange" variant="light" mt="xl" icon={<IconInfoCircle size={18}/>} title="测量边界">
            {report.meta.disclaimer}
          </Alert>
          <Group mt="lg" gap="sm">
            <Button variant="light" disabled={!validModules.length||resultsLocked||!!busy} onClick={()=>exportSelected('report','pdf')} data-testid="candidate-download-report">导出诊断报告 PDF</Button>
            <Button variant="subtle" disabled={!validModules.length||resultsLocked||!!busy} onClick={()=>exportSelected('report','txt')}>导出诊断报告 TXT</Button>
          </Group>
          <Group justify="space-between" mt="xl">
            <Button variant="subtle" leftSection={<IconArrowLeft size={16}/>} onClick={()=>navigate(2)}>返回修改目标</Button>
            <Button rightSection={<IconArrowRight size={16}/>} disabled={!validModules.length||resultsLocked||!!busy}
              onClick={()=>navigate(4)} data-testid="candidate-next-todo">查看优化建议 · 逐项采纳</Button>
          </Group>
        </>}

        {step===4&&report&&<>
          <StepTitle code="05" title="记录真实修改，逐项完成优化">填写本人实际修改后再采纳到待办；采纳与完成是两次独立操作。示例只提供局部表达，不代写整篇简历。</StepTitle>
          {stale&&<Alert color="orange" mb="lg">本次报告只读或建议依据待重新确认。请返回核对简历与目标并重新诊断，再继续修改待办。</Alert>}
          {validModules.length<enabled.length&&<Alert color="orange" mb="lg">部分报告：建议仅来自已完成模块，关闭或失败模块未纳入检查。</Alert>}
          <Panel title="优化建议与修改待办" extra={<Status text={'已采纳 '+selected.length+' · 已完成 '+completed} color="indigo"/>}>
            <Group justify="space-between" mb="md" wrap="wrap">
              <Text size="sm" data-testid="candidate-completion">已完成 {completed} / {selected.length} 项待办 · 共 {suggestions.length} 条建议</Text>
              <label className="diag-filter">查看 <select aria-label="建议筛选" value={todoFilter} onChange={e=>setTodoFilter(e.currentTarget.value)}>
                <option value="all">全部建议</option><option value="pending">待处理</option><option value="adopted">已采纳 · 待办</option>
                <option value="completed">已完成</option><option value="ignored">已忽略</option><option value="needs_confirmation">待重新确认</option>
              </select></label>
            </Group>
            {!suggestions.length&&<Text size="sm" c="dimmed">当前有效诊断未发现可执行的修改问题，不为凑数生成建议。</Text>}
            {suggestions.filter(s=>todoFilter==='all'||(modifications[s.id]?.status||'pending')===todoFilter).map(s=>{
              const modification=modifications[s.id]||{status:'pending',text:''};
              const text=editTexts[s.id]??modification.text??'';
              const changed=text!==(modification.text||'');
              const statusLabel={pending:'待处理',adopted:'已采纳 · 待办',completed:'已完成',ignored:'已忽略',needs_confirmation:'待重新确认'}[modification.status]||'待处理';
              const sources=s.source_modules||[s.source_module||s.module].filter(Boolean);
              return <div className="diag-advice" key={s.id} data-testid={'advice-'+s.id}>
              <Group gap="sm" wrap="wrap"><Status text={s.priority+'优先级'} color={s.priority==='高'?'orange':s.priority==='中'?'blue':'gray'}/>
                <Status text={s.assessment||'需要修正'} color={s.assessment==='可选深化'?'gray':'orange'}/><strong>{s.title}</strong>
                <Status text={statusLabel} color={modification.status==='completed'?'teal':'gray'}/></Group>
              <div className="diag-advice-body">
                {sources.length>0&&<Text size="xs" c="dimmed">来源：{sources.map(id=>SECTIONS.find(([key])=>key===id)?.[1]||id).join('、')}</Text>}
                <Text size="xs" c="dimmed">定位：{s.location}</Text>
                {!stale&&s.location&&<Button size="xs" variant="subtle" onClick={()=>locateEvidence(s.location)}>定位原文与字段</Button>}
                <Text size="sm">原文：{s.original}</Text>
                {s.related_location&&<Text size="sm" data-testid="advice-opposing-claim">
                  对照：{s.related_location} · {s.related_original}
                </Text>}
                <Text size="sm"><strong>{s.assessment==='可选深化'?'优化机会：':'问题：'}</strong>{s.problem}</Text>
                <Text size="sm"><strong>建议：</strong>{s.action}</Text>
                <div className="diag-example"><Group justify="space-between" gap="xs"><strong>局部示例（不是事实陈述）</strong>
                  <Button size="xs" variant="subtle" onClick={async()=>{
                    try{await navigator.clipboard.writeText(s.example||'');setNavNotice('示例文字已复制，采纳与完成状态未改变。');}
                    catch{setError('复制未完成，请选中文字手动复制。');}
                  }}>复制示例</Button></Group><div>{s.example}</div></div>
                <Textarea mt="md" autosize minRows={3} label="实际修改内容" placeholder="请填写你依据本人真实情况做出的修改；不要直接认定示例中的占位内容属实。"
                  value={text} onChange={e=>{const value=e.currentTarget.value;setEditTexts(previous=>({...previous,[s.id]:value}));}}
                  ref={node=>{modificationInputs.current[s.id]=node;}} error={adoptionErrors[s.id]||undefined}/>
                {changed&&<Text size="xs" c="orange" mt={5}>当前文字尚未保存；保存编辑不会自动标记完成。</Text>}
                {modification.status==='completed'&&changed&&<Text size="xs" c="orange">你正在修改已完成内容，保存后将重新进入待办。</Text>}
                {modification.text&&<details className="diag-before-after"><summary>查看前后对照与操作时间</summary>
                  <Text size="sm">修改前：{s.original||'此处为本人补充内容，无原文'}</Text><Text size="sm">已保存修改：{modification.text}</Text>
                  {modification.adopted_at&&<Text size="xs">采纳时间：{modification.adopted_at}</Text>}
                  {modification.completed_at&&<Text size="xs">独立完成时间：{modification.completed_at}</Text>}
                </details>}
                <Group mt="md" gap="xs" wrap="wrap">
                  {['pending','needs_confirmation'].includes(modification.status)&&<Button size="xs" disabled={!!busy||resultsLocked} onClick={()=>suggestionAction(s,'adopt')}>采纳到待办</Button>}
                  {modification.status==='adopted'&&<Button size="xs" disabled={!!busy||resultsLocked} onClick={()=>suggestionAction(s,'complete')}>标记完成</Button>}
                  {modification.status==='completed'&&<Button size="xs" variant="light" disabled={!!busy||resultsLocked} onClick={()=>suggestionAction(s,'reopen')}>重新打开</Button>}
                  {changed&&<Button size="xs" variant="light" disabled={!!busy||resultsLocked} onClick={()=>suggestionAction(s,'save')}>保存修改草稿</Button>}
                  {['adopted','completed'].includes(modification.status)&&<Button size="xs" variant="subtle" disabled={!!busy||resultsLocked} onClick={()=>suggestionAction(s,'unadopt')}>取消采纳</Button>}
                  {modification.status==='ignored'?<Button size="xs" variant="light" disabled={!!busy||resultsLocked} onClick={()=>suggestionAction(s,'restore')}>恢复建议</Button>:
                    <Button size="xs" variant="subtle" color="gray" disabled={!!busy||resultsLocked} onClick={()=>suggestionAction(s,'ignore')}>忽略建议</Button>}
                </Group>
              </div>
            </div>;})}
            {!selected.length&&<Text size="sm" c="dimmed" mt="md">尚无有效待办。填写实际修改并采纳至少一条建议后，可导出优化清单。</Text>}
            {unsavedModifications&&<Text size="sm" c="orange" mt="md">有实际修改文字尚未保存，保存成功后再导出，避免文件与页面内容不一致。</Text>}
            <Group mt="lg" gap="sm" wrap="wrap">
              <Button disabled={!selected.length||!!busy||resultsLocked||unsavedModifications} onClick={()=>exportSelected('todo','txt')}
                leftSection={<IconDownload size={16}/>} data-testid="candidate-download-txt">导出优化待办 TXT</Button>
              <Button variant="light" disabled={!selected.length||!!busy||resultsLocked||unsavedModifications} onClick={()=>exportSelected('todo','pdf')}
                leftSection={<IconDownload size={16}/>} data-testid="candidate-download-pdf">导出优化待办 PDF</Button>
            </Group>
            <Alert color="blue" variant="light" mt="lg" title="继续完成岗位简历">
              把当前已核对的履历、目标岗位与已选建议交给经典编辑器。
              建议不会自动改写简历；进入后需要再次核对内容，才能导出 Word/PDF。
              数据仅在当前浏览器标签页中一次性交接，不发送给外部 AI。
            </Alert>
            <Button mt="md" variant="light" leftSection={<IconFileText size={17}/>}
              onClick={openClassicWithReviewedDraft} disabled={!!busy||resultsLocked||!draft.review_confirmed||unsavedModifications}
              data-testid="candidate-open-classic">继续编辑并导出岗位简历</Button>
          </Panel>
          <Panel title="面试准备清单" extra={<Status text={questionList.length+' 条'} color="gray"/>}>
            {(questionList.length===0)&&<Text size="sm" c="dimmed">暂未发现需要准备的高/中风险追问，不编造回答或证明材料。</Text>}
            {questionList.map(q=><div className="diag-question" key={q.id}>
              <strong>可能追问的经历：{q.check}</strong>
              <Text size="sm" mt={6}>追问示例：{q.question}</Text>
              <Text size="sm">建议准备的说明／证据：{q.preparation||q.preparation_guidance||q.purpose}</Text>
              {q.source_issue_id&&<Text size="xs" c="dimmed">关联风险：{q.source_issue_id}</Text>}
            </div>)}
            <Group mt="lg"><Button size="sm" variant="light"
              disabled={!questionList.length||!!busy||resultsLocked} onClick={()=>exportSelected('questions','txt')}>导出面试准备 TXT</Button>
              <Button size="sm" variant="light"
              disabled={!questionList.length||!!busy||resultsLocked} onClick={()=>exportSelected('questions','pdf')}>导出面试准备 PDF</Button></Group>
          </Panel>
          <Group justify="space-between" mt="xl"><Button variant="subtle" leftSection={<IconArrowLeft size={16}/>} onClick={()=>navigate(3)}>返回诊断报告</Button>
            <Button variant="light" leftSection={<IconRefresh size={15}/>} onClick={()=>navigate(1)}>重新校对简历</Button></Group>
        </>}

        <div className="diag-footer"><span>PaperPro · Candidate Intelligence</span><span>规则透明 · 逐条证据 · 人工确认 · 不自动修改原简历</span></div>
      </main>
    </div>
  </div>;
}
