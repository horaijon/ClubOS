import "@fontsource-variable/manrope";
import { lazy, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import Entry from './Entry';
import './styles.css';
import './theme.css';
import './brand.css';
import './brutal.css';
import './modules.css';
import './launch.css';
import './polish.css';

const PublicRegistration=lazy(()=>import('./PublicRegistration'));
const registration=location.pathname.match(/^\/register\/([a-f0-9]+)\/?$/);
createRoot(document.getElementById('root')!).render(registration?<Suspense fallback={<p role="status">Loading registration…</p>}><PublicRegistration slug={registration[1]}/></Suspense>:<Entry/>);
