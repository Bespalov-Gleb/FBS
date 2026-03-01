import { useLocation } from 'react-router-dom';
import { Box } from '@mui/material';
import Breadcrumbs from './Breadcrumbs';

const routeLabels: Record<string, string> = {
  assembly: 'Сборка',
  account: 'Учетная запись',
  marketplaces: 'Маркетплейсы',
  'print-settings': 'Диспетчер',
  users: 'Пользователи',
};

export default function Header() {
  const location = useLocation();
  const pathSegments = location.pathname.split('/').filter(Boolean);
  const breadcrumbs = pathSegments.map((seg) => ({
    label: routeLabels[seg] ?? seg,
    path: '/' + pathSegments.slice(0, pathSegments.indexOf(seg) + 1).join('/'),
  }));

  return (
    <Box sx={{ borderBottom: 1, borderColor: 'divider', py: 1.5, px: 2 }}>
      <Breadcrumbs items={breadcrumbs} />
    </Box>
  );
}
