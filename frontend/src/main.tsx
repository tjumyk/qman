import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createTheme, MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import App from './App'
import { I18nProvider } from './i18n'
import { store } from './store'

const theme = createTheme({
  fontFamily:
    "-apple-system, BlinkMacSystemFont, Helvetica Neue, PingFang SC, Microsoft YaHei, Source Han Sans SC, Noto Sans CJK SC, WenQuanYi Micro Hei, Arial, Helvetica, sans-serif",
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1 },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <MantineProvider theme={theme} defaultColorScheme="auto">
          <I18nProvider>
            <Notifications position="top-right" />
            <App />
          </I18nProvider>
        </MantineProvider>
      </QueryClientProvider>
    </Provider>
  </StrictMode>,
)
