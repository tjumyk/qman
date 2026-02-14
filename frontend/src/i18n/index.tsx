import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

const STORAGE_KEY = 'qman-locale'

export type Locale = 'en' | 'zh-Hans'

function getDefaultLocale(): Locale {
  if (typeof window === 'undefined') return 'en'
  const stored = localStorage.getItem(STORAGE_KEY) as Locale | null
  if (stored === 'zh-Hans' || stored === 'en') return stored
  const browser = navigator.language
  return browser.startsWith('zh') ? 'zh-Hans' : 'en'
}

const translations: Record<Locale, Record<string, string>> = {
  en: {
    appTitle: 'DQMS',
    appDescription: 'Disk Quota Management System',
    loading: 'Loading...',
    notSignedIn: 'Not signed in',
    pleaseLogin: 'Please log in to use Quota Manager.',
    myUsage: 'My usage',
    dashboard: 'Dashboard',
    byHost: 'By host',
    myProfile: 'My profile',
    logOut: 'Log out',
    footer: '©Kelvin, 2016.',
    themeLight: 'Light',
    themeDark: 'Dark',
    langEn: 'En',
    langZh: '中文',
    admin: 'admin',
    // Status
    statusOk: 'OK',
    statusNearLimit: 'Near limit',
    statusOverLimit: 'Over limit',
    // Errors & loading
    error: 'Error',
    failedToLoadQuotas: 'Failed to load quotas',
    missingHost: 'Missing host',
    missingHostOrDevice: 'Missing host or device',
    deviceNotFound: 'Device not found',
    hostNotFoundOrError: 'Host not found or error',
    loadingYourQuotas: 'Loading your quotas...',
    // Pages & sections
    hosts: 'Hosts',
    devices: 'Devices',
    devicesWithQuota: 'Devices (with quota)',
    userQuotas: 'User quotas',
    totalHosts: 'Total hosts',
    totalDevices: 'Total devices',
    usersOverSoft: 'Users over soft limit',
    usersOverHard: 'Users over hard limit',
    needsAttention: 'Needs attention',
    noUsersOverLimit: 'No users over soft or hard limit.',
    noQuotas: 'No quotas',
    noQuotasAssigned: 'You have no quota assignments on any host.',
    yourQuotaUsage: 'Your quota usage',
    noUsersMatch: 'No users match.',
    needAttentionCount: 'need attention',
    // Table & form
    searchByNameOrUid: 'Search by name or uid...',
    edit: 'Edit',
    cancel: 'Cancel',
    save: 'Save',
    actions: 'Actions',
    editQuota: 'Edit quota',
    blockSoftLimit1k: 'Block soft limit (1K blocks)',
    blockHardLimit1k: 'Block hard limit (1K blocks)',
    inodeSoftLimit: 'Inode soft limit',
    inodeHardLimit: 'Inode hard limit',
    quotaUpdated: 'Quota updated',
    failedToUpdateQuota: 'Failed to update quota',
    blockUsage: 'Block usage',
    inodeUsage: 'Inode usage',
    // Counts (use with number: e.g. "5 device(s)")
    deviceCount: 'device(s)',
    userCount: 'user(s)',
    // Table headers
    uid: 'uid',
    name: 'name',
    blockUsed: 'block used',
    blockSoft: 'block soft',
    blockHard: 'block hard',
    inodeUsed: 'inode used',
    inodeSoft: 'inode soft',
    inodeHard: 'inode hard',
    status: 'status',
    // Host detail
    hostDevicesTitle: 'devices',
  },
  'zh-Hans': {
    appTitle: 'DQMS',
    appDescription: '磁盘配额管理系统',
    loading: '加载中…',
    notSignedIn: '未登录',
    pleaseLogin: '请登录以使用配额管理。',
    myUsage: '我的用量',
    dashboard: '仪表盘',
    byHost: '按主机',
    myProfile: '个人资料',
    logOut: '退出登录',
    footer: '©Kelvin, 2016.',
    themeLight: '浅色',
    themeDark: '深色',
    langEn: 'En',
    langZh: '中文',
    admin: '管理员',
    statusOk: '正常',
    statusNearLimit: '接近限制',
    statusOverLimit: '超出限制',
    error: '错误',
    failedToLoadQuotas: '加载配额失败',
    missingHost: '缺少主机',
    missingHostOrDevice: '缺少主机或设备',
    deviceNotFound: '未找到设备',
    hostNotFoundOrError: '未找到主机或出错',
    loadingYourQuotas: '正在加载您的配额…',
    hosts: '主机',
    devices: '设备',
    devicesWithQuota: '设备（含配额）',
    userQuotas: '用户配额',
    totalHosts: '主机总数',
    totalDevices: '设备总数',
    usersOverSoft: '超过软限制的用户',
    usersOverHard: '超过硬限制的用户',
    needsAttention: '需关注',
    noUsersOverLimit: '没有超过软/硬限制的用户。',
    noQuotas: '无配额',
    noQuotasAssigned: '您在任何主机上都没有配额分配。',
    yourQuotaUsage: '您的配额用量',
    noUsersMatch: '没有匹配的用户。',
    needAttentionCount: '需关注',
    searchByNameOrUid: '按姓名或 uid 搜索…',
    edit: '编辑',
    cancel: '取消',
    save: '保存',
    actions: '操作',
    editQuota: '编辑配额',
    blockSoftLimit1k: '块软限制（1K 块）',
    blockHardLimit1k: '块硬限制（1K 块）',
    inodeSoftLimit: 'Inode 软限制',
    inodeHardLimit: 'Inode 硬限制',
    quotaUpdated: '配额已更新',
    failedToUpdateQuota: '更新配额失败',
    blockUsage: '块用量',
    inodeUsage: 'Inode 用量',
    deviceCount: '台设备',
    userCount: '个用户',
    uid: 'uid',
    name: '名称',
    blockUsed: '块已用',
    blockSoft: '块软限',
    blockHard: '块硬限',
    inodeUsed: 'inode 已用',
    inodeSoft: 'inode 软限',
    inodeHard: 'inode 硬限',
    status: '状态',
    hostDevicesTitle: '设备',
  },
}

type I18nContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getDefaultLocale)

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    localStorage.setItem(STORAGE_KEY, next)
  }, [])

  const t = useCallback(
    (key: string) => {
      const map = translations[locale]
      return map[key] ?? key
    },
    [locale]
  )

  const value = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t]
  )

  return (
    <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
  )
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within I18nProvider')
  return ctx
}
