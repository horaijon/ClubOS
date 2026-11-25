import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

export function Dialog({title,onClose,children,compact=false}:{title:string;onClose:()=>void;children:ReactNode;compact?:boolean}) {
 const ref=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const dialog=ref.current;const last=document.activeElement as HTMLElement|null;dialog?.showModal();return()=>{dialog?.close();if(last?.isConnected)last.focus();}},[]);
 return <dialog ref={ref} className={'shell-dialog'+(compact?' compact':'')} aria-label={title} onCancel={e=>{e.preventDefault();onClose()}} onClick={e=>{if(e.target===ref.current){const rect=ref.current.getBoundingClientRect();if(e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)onClose()}}}>
 <header className="dialog-top"><h2>{title}</h2><button className="icon-button" autoFocus={!compact} onClick={onClose} aria-label="Close dialog"><X size={18}/></button></header>{children}
 </dialog>
}
