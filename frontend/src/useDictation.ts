import { useEffect, useRef, useState } from 'react'

interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((event:{results:ArrayLike<ArrayLike<{transcript:string}>>})=>void)|null
  onend: (()=>void)|null
  onerror: (()=>void)|null
  start():void
  stop():void
  abort():void
}
const speech=window as Window & {SpeechRecognition?:new()=>Recognition;webkitSpeechRecognition?:new()=>Recognition}
const Recognizer=speech.SpeechRecognition||speech.webkitSpeechRecognition

export function useDictation(){
  const active=useRef<Recognition|null>(null)
  const [listening,setListening]=useState(false),[error,setError]=useState('')
  useEffect(()=>()=>{active.current?.abort()},[])
  function toggle(current:string,update:(value:string)=>void){
    if(active.current){active.current.stop();return}
    if(!Recognizer)return
    setError('')
    const recognition=new Recognizer()
    recognition.lang='en-IN'
    recognition.interimResults=true
    recognition.continuous=true
    recognition.onresult=event=>update([current.trim(),...Array.from(event.results,result=>result[0].transcript)].filter(Boolean).join(' '))
    recognition.onend=()=>{active.current=null;setListening(false)}
    recognition.onerror=()=>setError('Dictation stopped. Check microphone permissions or type your brief.')
    try{recognition.start();active.current=recognition;setListening(true)}
    catch{setError('The microphone could not start. Type your brief to continue.')}
  }
  return {supported:Boolean(Recognizer),listening,error,toggle}
}
