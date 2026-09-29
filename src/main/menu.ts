import { Menu, shell, type BrowserWindow } from 'electron'
import type { MenuAction } from '@shared/types'

function send(win: BrowserWindow, action: MenuAction): void {
  win.webContents.send('menu:action', action)
}

export function buildAppMenu(win: BrowserWindow): Menu {
  const m = (label: string, action: MenuAction, accelerator?: string, enabled = true) => ({
    label,
    accelerator,
    enabled,
    click: () => send(win, action)
  })

  const menu = Menu.buildFromTemplate([
    {
      label: '文件',
      submenu: [
        m('新建', 'new', 'CmdOrCtrl+N'),
        m('打开…', 'open', 'CmdOrCtrl+O'),
        m('打开文件夹…', 'open-folder', 'CmdOrCtrl+Shift+O'),
        { type: 'separator' },
        m('保存', 'save', 'CmdOrCtrl+S'),
        m('另存为…', 'save-as', 'CmdOrCtrl+Shift+S'),
        { type: 'separator' },
        {
          label: '导出',
          submenu: [
            m('HTML', 'export-html'),
            m('PDF…', 'export-pdf'),
            m('PNG 图片', 'export-png'),
            m('JPEG 图片', 'export-jpeg'),
            { type: 'separator' },
            m('Word (docx, 需 Pandoc)', 'export-docx'),
            m('ePub (需 Pandoc)', 'export-epub'),
            m('LaTeX (需 Pandoc)', 'export-latex'),
            m('ODT (需 Pandoc)', 'export-odt')
          ]
        },
        { type: 'separator' },
        m('关闭文件夹', 'close-folder'),
        { role: 'quit', label: '退出' }
      ]
    },
    {
      label: '编辑',
      submenu: [
        { role: 'undo', label: '撤销' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '复制' },
        { role: 'paste', label: '粘贴' },
        { role: 'selectAll', label: '全选' },
        { type: 'separator' },
        m('查找…', 'find', 'CmdOrCtrl+F')
      ]
    },
    {
      label: '格式',
      submenu: [
        m('加粗', 'bold', 'CmdOrCtrl+B'),
        m('斜体', 'italic', 'CmdOrCtrl+I'),
        m('删除线', 'strikethrough', 'CmdOrCtrl+Shift+X'),
        m('行内代码', 'inline-code', 'CmdOrCtrl+Shift+`'),
        m('代码块', 'code-block', 'CmdOrCtrl+Shift+K'),
        { type: 'separator' },
        m('链接', 'link', 'CmdOrCtrl+K'),
        m('图片', 'image', 'CmdOrCtrl+Shift+I'),
        m('引用块', 'quote'),
        m('表格', 'table'),
        m('数学公式块', 'math'),
        m('分隔线', 'hr')
      ]
    },
    {
      label: '视图',
      submenu: [
        m('切换源码 / 实时视图', 'toggle-source', 'CmdOrCtrl+/'),
        m('切换侧边栏', 'toggle-sidebar', 'CmdOrCtrl+J'),
        { type: 'separator' },
        m('专注模式', 'toggle-focus', 'F8'),
        m('打字机模式', 'toggle-typewriter', 'F9'),
        m('文件面板', 'files-tab'),
        m('大纲面板', 'outline-tab'),
        { type: 'separator' },
        { role: 'togglefullscreen', label: '全屏' },
        m('放大', 'zoom-in', 'CmdOrCtrl+='),
        m('缩小', 'zoom-out', 'CmdOrCtrl+-'),
        m('恢复默认字号', 'actual-size', 'CmdOrCtrl+0')
      ]
    },
    {
      label: '帮助',
      submenu: [
        m('设置', 'settings', 'CmdOrCtrl+,'),
        m('打开自定义 CSS', 'open-custom-css'),
        {
          label: 'Markdown 语法帮助',
          click: () => shell.openExternal('https://markdown.com.cn/basic-syntax/').catch(() => {})
        },
        {
          label: '关于 MdNote',
          click: () => send(win, 'about')
        }
      ]
    }
  ])
  return menu
}
