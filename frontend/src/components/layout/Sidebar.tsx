import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Typography,
  IconButton,
  Menu,
  MenuItem,
  Avatar,
} from '@mui/material';
import MoreVert from '@mui/icons-material/MoreVert';
import {
  Inventory2,
  Person,
  Store,
  Print,
  People,
} from '@mui/icons-material';
import { palette } from '../../theme/theme';
import { logout } from '../../store/authSlice';
import type { RootState } from '../../store';

const DRAWER_WIDTH = 260;

const menuItems = [
  { path: '/assembly', label: 'Сборка', icon: <Inventory2 />, roles: ['admin', 'packer'] },
  { path: '/account', label: 'Учетная запись', icon: <Person />, roles: ['admin', 'packer'] },
  { path: '/marketplaces', label: 'Маркетплейсы', icon: <Store />, roles: ['admin', 'packer'] },
  { path: '/print-settings', label: 'Диспетчер печати', icon: <Print />, roles: ['admin', 'packer'] },
  { path: '/users', label: 'Пользователи', icon: <People />, roles: ['admin'] },
];

export default function Sidebar() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const user = useSelector((state: RootState) => state.auth.user);
  const userRole = (user?.role as 'admin' | 'packer') ?? 'packer';
  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null);

  const visibleItems = menuItems.filter((item) => item.roles.includes(userRole));

  const handleLogout = () => {
    setMenuAnchor(null);
    dispatch(logout());
    navigate('/login');
  };

  return (
    <Drawer
      variant="permanent"
      sx={{
        width: DRAWER_WIDTH,
        flexShrink: 0,
        '& .MuiDrawer-paper': {
          width: DRAWER_WIDTH,
          boxSizing: 'border-box',
          bgcolor: palette.sidebar.dark,
          color: palette.text.onDark,
          display: 'flex',
          flexDirection: 'column',
        },
      }}
    >
      <Box sx={{ p: 2 }}>
        <Typography variant="h6" fontWeight={600}>
          FBS.tools
        </Typography>
      </Box>
      {user && (
        <Box sx={{ px: 2, py: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
          <Avatar sx={{ width: 36, height: 36, bgcolor: palette.sidebar.lighter }}>
            {user.full_name?.charAt(0) ?? '?'}
          </Avatar>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="body2" noWrap>
              {user.full_name}
            </Typography>
            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.7)' }}>
              {user.role === 'admin' ? 'Админ' : 'Упаковщик'}
            </Typography>
          </Box>
          <IconButton
            size="small"
            sx={{ color: 'inherit' }}
            onClick={(e) => setMenuAnchor(e.currentTarget)}
          >
            <MoreVert />
          </IconButton>
        </Box>
      )}
      <Menu
        anchorEl={menuAnchor}
        open={!!menuAnchor}
        onClose={() => setMenuAnchor(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
      >
        <MenuItem onClick={() => { setMenuAnchor(null); navigate('/account'); }}>
          Учетная запись
        </MenuItem>
        <MenuItem onClick={handleLogout}>Выйти</MenuItem>
      </Menu>
      <List sx={{ flex: 1 }}>
        {visibleItems.map((item) => (
          <ListItemButton
            key={item.path}
            selected={location.pathname === item.path}
            onClick={() => navigate(item.path)}
            sx={{
              '&.Mui-selected': {
                bgcolor: palette.sidebar.lighter,
              },
            }}
          >
            <ListItemIcon sx={{ color: 'inherit', minWidth: 40 }}>
              {item.icon}
            </ListItemIcon>
            <ListItemText primary={item.label} />
          </ListItemButton>
        ))}
      </List>
    </Drawer>
  );
}
