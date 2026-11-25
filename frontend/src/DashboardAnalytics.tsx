import { useMemo, type CSSProperties } from 'react'
import { Download } from 'lucide-react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { shortDate, type Snapshot } from './data'

import { PeriodControl, type Period } from './PeriodControl'

export function eventSeries(data:Snapshot, days:Period) {
  const registrations = new Map<string,number>()
  const runs = new Map<string,{completed:number; review:number}>()
  if(data.registration_history?.length){
    for(const row of data.registration_history)registrations.set(row.date.slice(0,10),row.count)
  }else{
    for(const participant of data.participants){
      const day=participant.created_at?.slice(0,10)
      if(day)registrations.set(day,(registrations.get(day)??0)+1)
    }
  }
  for(const run of data.runs){
    const day=run.created_at?.slice(0,10)
    if(!day)continue
    const counts=runs.get(day)??{completed:0,review:0}
    if(run.status==='Completed')counts.completed++
    if(run.status==='Awaiting Approval')counts.review++
    runs.set(day,counts)
  }
  const first=new Date()
  first.setUTCHours(0,0,0,0)
  first.setUTCDate(first.getUTCDate()-days+1)
  const start=first.toISOString().slice(0,10)
  let total=0
  for(const [day,count] of registrations)if(day<start)total+=count
  return Array.from({length:days},(_,index)=>{
    const date=new Date(first)
    date.setUTCDate(date.getUTCDate()+index)
    const day=date.toISOString().slice(0,10)
    const signups=registrations.get(day)??0
    total+=signups
    return {day,signups,total,...(runs.get(day)??{completed:0,review:0})}
  })
}
type Series = ReturnType<typeof eventSeries>
const axis={fill:'var(--muted)',fontSize:12}
const tooltip={background:'var(--surface)',border:'1px solid var(--line)',borderRadius:12,color:'var(--text)',fontSize:13}
const chartDate=(day:unknown)=>shortDate(String(day))

function Chart({series, automation}:{series:Series;automation?:boolean}){
  const xAxis=<XAxis dataKey="day" tickFormatter={chartDate} axisLine={false} tickLine={false} minTickGap={27} tickMargin={10} tick={axis}/>
  const yAxis=<YAxis allowDecimals={false} axisLine={false} tickLine={false} width={30} tick={axis}/>
  const grid=<CartesianGrid stroke="var(--line)" strokeDasharray="3 5" vertical={false}/>
  const hint=<Tooltip contentStyle={tooltip} labelFormatter={chartDate}/>
  return <div className="dash-chart">
    <ResponsiveContainer width="100%" height="100%" minWidth={0}>
      {automation ? <BarChart data={series} margin={{right:8,top:8,bottom:5}} maxBarSize={32}>
        {grid}{xAxis}{yAxis}{hint}
        <Bar dataKey="completed" name="Completed" stackId="runs" fill="var(--cobalt)" isAnimationActive={false}/>
        <Bar dataKey="review" name="Awaiting approval" stackId="runs" fill="#84ad39" radius={[5,5,0,0]} isAnimationActive={false}/>
      </BarChart> : <AreaChart data={series} margin={{right:12,top:8,bottom:5}}>
        <defs><linearGradient id="dash-registration-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="var(--cobalt)" stopOpacity=".26"/><stop offset="100%" stopColor="var(--cobalt)" stopOpacity=".04"/></linearGradient></defs>
        {grid}{xAxis}{yAxis}{hint}
        <Area dataKey="total" name="Total registrations" type="monotone" stroke="var(--cobalt)" strokeWidth={2.5} fill="url(#dash-registration-fill)" isAnimationActive={false}/>
      </AreaChart>}
    </ResponsiveContainer>
  </div>
}

export function AutomationChart({data, days}:{data:Snapshot;days:Period}){
  const series=useMemo(()=>eventSeries(data,days),[data,days])
  const completed=series.reduce((sum,day)=>sum+day.completed,0)
  const review=series.reduce((sum,day)=>sum+day.review,0)
  return <section className="dash-panel dash-detail-panel" aria-label={`Automation activity over ${days} days. ${completed} completed records and ${review} routed for approval.`}>
    <div className="dash-panel-heading"><h2>Automation activity</h2><p>Recorded completions and reviews · last {days} days</p></div>
    <div className="dash-legend"><span><i/>{completed} completed</span><span><i className="legend-review"/>{review} awaiting approval</span></div>
    <Chart series={series} automation/>
  </section>
}

const taskGroups=[
  {label:'Completed',color:'var(--cobalt)'},
  {label:'In Progress',color:'#6985ee'},
  {label:'Review',color:'#83ae3e'},
  {label:'Blocked',color:'#a5485a'},
  {label:'To Do',color:'#bfcdf3'},
]
function TaskBreakdown({data}:{data:Snapshot}){
  const counts=new Map<string,number>()
  for(const task of data.tasks)counts.set(task.status,(counts.get(task.status)??0)+1)
  const segments=taskGroups.map(item=>({...item,count:counts.get(item.label)??0}))
  const total=segments.reduce((sum,item)=>sum+item.count,0)
  const circumference=2*Math.PI*42
  let offset=0
  return <section className="dash-panel dash-detail-panel">
    <div className="dash-panel-heading"><h2>Tasks by status</h2><p>Current event snapshot</p></div>
    <div className="dash-ring">
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r="42" stroke="var(--raised)"/>
        {segments.filter(item=>item.count>0).map(item=>{
          const length=item.count/total*circumference
          const start=offset
          offset+=length
          return <circle key={item.label} cx="50" cy="50" r="42" stroke={item.color} strokeDasharray={`${Math.max(0,length-1.5)} ${circumference}`} strokeDashoffset={-start}/>
        })}
      </svg>
      <div><strong>{total}</strong><span>Tasks</span></div>
    </div>
    <ul className="dash-breakdown">{segments.map(item=><li key={item.label} style={{'--segment':item.color} as CSSProperties}><span><i/>{item.label}</span><strong>{item.count}</strong></li>)}</ul>
  </section>
}

function exportSeries(series:Series){
  const csv=['date,new_registrations,total_registrations,completed_runs,approval_runs',...series.map(row=>[row.day,row.signups,row.total,row.completed,row.review].join(','))].join('\n')
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}))
  const link=document.createElement('a')
  link.href=url
  link.download='clubos-event-trends.csv'
  link.click()
  setTimeout(()=>URL.revokeObjectURL(url),1000)
}

export function Trends({data,days,setDays}:{data:Snapshot;days:Period;setDays:(days:Period)=>void}){
  const series=useMemo(()=>eventSeries(data,days),[data,days])
  const signups=series.reduce((sum,row)=>sum+row.signups,0)
  const completed=series.reduce((sum,row)=>sum+row.completed,0)
  const review=series.reduce((sum,row)=>sum+row.review,0)
  return <div className="dash-workspace">
    <div className="dash-heading">
      <div><h1>Event trends</h1><p>{data.event.name}</p></div>
      <div className="dash-heading-actions"><PeriodControl value={days} onChange={setDays}/><button className="subtle-button" onClick={()=>exportSeries(series)}><Download size={16}/> Export CSV</button></div>
    </div>
    <section className="dash-trend-stats" aria-label="Event trend metrics">
      {[['New registrations',signups],['Completed runs',completed],['Runs sent for review',review]].map(([label,value])=><div className="dash-panel dash-trend-stat" key={label}><span>{label}</span><strong>{value}</strong><small>Last {days} days</small></div>)}
    </section>
    <div className="dash-detail-grid">
      <section className="dash-panel dash-detail-panel" aria-label={`Registration trend with ${signups} new signups in ${days} days`}>
        <div className="dash-panel-heading"><h2>Registration growth</h2><p>Cumulative signups across the selected period</p></div>
        <Chart series={series}/>
      </section>
      <TaskBreakdown data={data}/>
    </div>
    <AutomationChart data={data} days={days}/>
  </div>
}
