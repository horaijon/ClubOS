export type Period = 7 | 30 | 90

export function PeriodControl({value, onChange}:{value:Period;onChange:(period:Period)=>void}){
  return <div className="dash-period" role="group" aria-label="Chart date range">
    {([7,30,90] as const).map(days=><button key={days} type="button" aria-pressed={value===days} onClick={()=>onChange(days)}>{days} days</button>)}
  </div>
}
