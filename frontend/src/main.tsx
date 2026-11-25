import "@fontsource-variable/manrope";
import { createRoot } from 'react-dom/client';
import Entry from './Entry';
import './styles.css';
import './theme.css';

createRoot(document.getElementById('root')!).render(<Entry/>);
