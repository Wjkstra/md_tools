/// <reference types="vite/client" />

import type { MdNoteAPI } from '../../../shared/types'

declare global {
  interface Window {
    mdnote: MdNoteAPI
  }
}

export {}
