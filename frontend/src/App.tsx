import {
  Container,
  AppShell,
  Title,
  Text,
  NavLink,
  Loader,
  Alert,
  Group,
  Box,
  Stack,
  Menu,
  UnstyledButton,
  SegmentedControl,
  Burger,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure, useMediaQuery } from '@mantine/hooks'
import { IconSun, IconMoon, IconUser, IconGauge, IconChartBar, IconServer, IconLink } from '@tabler/icons-react'
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate, useLocation, Outlet } from 'react-router-dom'
import { fetchMe } from './api'
import { useI18n } from './i18n'
import { MyUsagePage } from './pages/MyUsagePage'
import { MyMappingsPage } from './pages/MyMappingsPage'
import { DashboardPage } from './pages/DashboardPage'
import { HostListPage } from './pages/HostListPage'
import { HostDetailPage } from './pages/HostDetailPage'
import { DeviceUserListPage } from './pages/DeviceUserListPage'
import { AdminMappingsPage } from './pages/AdminMappingsPage'
import { PageBreadcrumbs } from './components/PageBreadcrumbs'

function AppShellWithNav() {
  const [opened, { toggle, close }] = useDisclosure(false)
  const { data: me, isLoading, error } = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  const navigate = useNavigate()
  const location = useLocation()
  const { t, locale, setLocale } = useI18n()
  const { setColorScheme } = useMantineColorScheme()
  const computedColorScheme = useComputedColorScheme('light')
  const isMobile = useMediaQuery('(max-width: 36em)')

  const navTo = (path: string) => {
    close()
    navigate(path)
  }

  // Close mobile navbar when route changes (e.g. back/forward or in-page links)
  useEffect(() => {
    close()
  }, [location.pathname, close])

  const themeAndLocaleControls = (
    <Group gap="sm">
      <SegmentedControl
        size="xs"
        value={computedColorScheme}
        onChange={(v) => setColorScheme(v as 'light' | 'dark')}
        data={[
          {
            label: (
              <Box component="span" display="flex" style={{ alignItems: 'center', justifyContent: 'center' }}>
                <IconSun size={16} />
              </Box>
            ),
            value: 'light',
          },
          {
            label: (
              <Box component="span" display="flex" style={{ alignItems: 'center', justifyContent: 'center' }}>
                <IconMoon size={16} />
              </Box>
            ),
            value: 'dark',
          },
        ]}
      />
      <SegmentedControl
        size="xs"
        value={locale}
        onChange={(v) => setLocale(v as 'en' | 'zh-Hans')}
        data={[
          { label: t('langZh'), value: 'zh-Hans' },
          { label: t('langEn'), value: 'en' },
        ]}
      />
    </Group>
  )

  if (isLoading) {
    return (
      <Container size="xl" py="xl">
        <Loader size="lg" />
        <Text c="dimmed">{t('loading')}</Text>
      </Container>
    )
  }
  if (error || !me) {
    return (
      <Container size="xl" py="xl">
        <Alert color="red" title={t('notSignedIn')}>
          {t('pleaseLogin')}
        </Alert>
      </Container>
    )
  }

  return (
    <AppShell
      header={{ height: 56 }}
      padding={{ base: 'xs', sm: 'md' }}
      navbar={{
        width: 220,
        breakpoint: 'sm',
        collapsed: { mobile: !opened },
      }}
    >
      <AppShell.Header>
        <Container size="xl" h="100%" display="flex" style={{ alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0, flex: '1 1 auto' }}>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <UnstyledButton
              component={Link}
              to="/"
              display="flex"
              style={{ alignItems: 'center', textDecoration: 'none', color: 'inherit', minWidth: 0 }}
            >
              <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
                <Box
                  component="img"
                  src={computedColorScheme === 'dark' ? '/logo-dark.svg' : '/logo.svg'}
                  alt=""
                  h={32}
                  w="auto"
                  style={{ display: 'block', flexShrink: 0 }}
                />
                <Stack gap={2} style={{ minWidth: 0 }}>
                  <Title order={3} style={{ lineHeight: 1.2 }}>
                    {t('appTitle')}
                  </Title>
                  <Text size="xs" c="dimmed" style={{ lineHeight: 1.2 }} visibleFrom="sm">
                    {t('appDescription')}
                  </Text>
                </Stack>
              </Group>
            </UnstyledButton>
          </Group>
          <Group gap="sm" wrap="wrap" style={{ marginLeft: 'auto', flexShrink: 0 }}>
            {!isMobile && themeAndLocaleControls}
            <Menu shadow="md" width={isMobile ? 260 : 200} position="bottom-end" trigger={isMobile ? 'click' : 'hover'} openDelay={100} closeDelay={150}>
            <Menu.Target>
              <UnstyledButton style={{ cursor: 'pointer' }}>
                <Group gap="xs">
                  <IconUser size={16} />
                  <Text size="sm" c="dimmed">
                    {me.name}
                    {me.is_admin ? ` (${t('admin')})` : ''}
                  </Text>
                </Group>
              </UnstyledButton>
            </Menu.Target>
            <Menu.Dropdown>
              {isMobile && (
                <>
                  <Stack gap="xs" p="xs">
                    {themeAndLocaleControls}
                  </Stack>
                  <Menu.Divider />
                </>
              )}
              <Menu.Item component="a" href="/account/profile">
                {t('myProfile')}
              </Menu.Item>
              <Menu.Item component="a" href="/account/logout">
                {t('logOut')}
              </Menu.Item>
            </Menu.Dropdown>
            </Menu>
          </Group>
        </Container>
      </AppShell.Header>
      <AppShell.Navbar p="md">
        <AppShell.Section>
          <NavLink
            leftSection={<IconChartBar size={18} />}
            label={t('myUsage')}
            active={location.pathname === '/my-usage'}
            onClick={() => navTo('/my-usage')}
          />
          <NavLink
            leftSection={<IconLink size={18} />}
            label={t('myMappings')}
            active={location.pathname === '/my-mappings'}
            onClick={() => navTo('/my-mappings')}
          />
          {me.is_admin && (
            <>
              <NavLink
                leftSection={<IconGauge size={18} />}
                label={t('dashboard')}
                active={location.pathname === '/manage' || location.pathname === '/manage/'}
                onClick={() => navTo('/manage')}
              />
              <NavLink
                leftSection={<IconServer size={18} />}
                label={t('hostList')}
                active={location.pathname.startsWith('/manage/hosts')}
                onClick={() => navTo('/manage/hosts')}
              />
              <NavLink
                leftSection={<IconLink size={18} />}
                label={t('userMappings')}
                active={location.pathname === '/manage/mappings'}
                onClick={() => navTo('/manage/mappings')}
              />
            </>
          )}
        </AppShell.Section>
      </AppShell.Navbar>
      <AppShell.Main pb="xl">
        <Container size="xl">
          <PageBreadcrumbs />
          <Outlet />
        </Container>
      </AppShell.Main>
      <AppShell.Footer>
        <Container size="xl">
          <Text size="sm" c="dimmed">
            {t('footer')}
          </Text>
        </Container>
      </AppShell.Footer>
    </AppShell>
  )
}

function RootRedirect() {
  const { data: me } = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  if (me?.is_admin) return <Navigate to="/manage" replace />
  return <Navigate to="/my-usage" replace />
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<AppShellWithNav />}>
          <Route index element={<RootRedirect />} />
          <Route path="my-usage" element={<MyUsagePage />} />
          <Route path="my-mappings" element={<MyMappingsPage />} />
          <Route path="manage" element={<DashboardPage />} />
          <Route path="manage/hosts" element={<HostListPage />} />
          <Route path="manage/hosts/:hostId" element={<HostDetailPage />} />
          <Route path="manage/hosts/:hostId/devices/:deviceName" element={<DeviceUserListPage />} />
          <Route path="manage/mappings" element={<AdminMappingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
