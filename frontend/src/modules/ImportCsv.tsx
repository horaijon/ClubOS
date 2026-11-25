import { useState } from 'react'
import { Upload } from 'lucide-react'
import { Button, Dialog, Field, Notice, useAction } from './ui'
import type { ModuleProps, Row } from './ui'

function parseCsv(text:string,required:string[]):Row[] {
  const records:string[][]=[]
  let record:string[]=[], field='', quoted=false
  for(let i=0;i<text.length;i++){
    const char=text[i]
    if(char==='"'){
      if(quoted && text[i+1]==='"'){field+='"';i++}
      else quoted=!quoted
    }else if(char===',' && !quoted){record.push(field.trim());field=''}
    else if((char==='\n'||char==='\r')&&!quoted){
      if(char==='\r'&&text[i+1]==='\n')i++
      record.push(field.trim());if(record.some(Boolean))records.push(record)
      record=[];field=''
    }else field+=char
  }
  if(quoted)throw new Error('A quoted CSV field has no closing quote.')
  record.push(field.trim());if(record.some(Boolean))records.push(record)
  const [rawHeaders,...rows]=records
  const headers=(rawHeaders||[]).map(key=>key.toLowerCase().replace(/^\uFEFF/,''))
  if(!required.every(key=>headers.includes(key)))throw new Error('Required columns are '+required.join(', ')+'.')
  if(!rows.length||rows.length>500)throw new Error('Choose a CSV with 1 to 500 data rows.')
  return rows.map((row,i)=>{
    if(row.length!==headers.length)throw new Error('Check the number of columns on row '+(i+2)+'.')
    const values=Object.fromEntries(headers.map((key,j)=>[key,row[j]]))
    if(required.some(key=>!values[key]))throw new Error('Fill in the required fields on row '+(i+2)+'.')
    return values
  })
}
export default function ImportCsv({kind,act,onClose}:{kind:'sponsors'|'participants',act:ModuleProps['act'],onClose:()=>void}){
  const required=kind==='sponsors'?['name','industry']:['name','email']
  const state=useAction(act)
  const [rows,setRows]=useState<Row[]>([]),[error,setError]=useState('')
  return <Dialog title={'Import '+kind} onClose={onClose}><Notice state={state}/><div className="m-form"><p className="m-copy">Choose a CSV with columns <b>{required.join(', ')}</b>{kind==='sponsors'?' and an optional description':''}.</p><Field label="CSV file"><input type="file" accept=".csv,text/csv" onChange={async e=>{
    const file=e.target.files?.[0];setRows([]);setError('')
    try{if(!file)return;if(file.size>1024*1024)throw new Error('Choose a file smaller than 1 MB.');setRows(parseCsv(await file.text(),required))}catch(err){setError((err as Error).message)}
  }}/></Field>{error && <p className="m-notice error" role="alert">{error}</p>}{rows.length>0 && <p className="m-copy">{rows.length} records ready. First entry · {rows[0].name}</p>}<div className="m-actions"><Button disabled={!rows.length} busy={state.busy} primary onClick={()=>state.run('import_'+kind,{rows},undefined,onClose)}><Upload/> Import records</Button></div></div></Dialog>
}
