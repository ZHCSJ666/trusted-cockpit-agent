import React from 'react'
import ReactDOM from 'react-dom/client'
import Studio from './studio/Studio'
import './studio/studio.css'

// Keep the original application available for architecture walkthroughs.
if (new URLSearchParams(window.location.search).get('upstream') === '1') {
  void import('./upstream')
} else {
  document.title = '经纬 · 可信座舱 | Meridian Cockpit Lab'
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode><Studio /></React.StrictMode>,
  )
}
