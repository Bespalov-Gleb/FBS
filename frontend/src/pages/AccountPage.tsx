import { useState, useRef, useEffect } from 'react';
import {
  Box,
  Typography,
  Card,
  CardContent,
  Avatar,
  Chip,
  Skeleton,
  IconButton,
  Link,
  Divider,
} from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { useSelector } from 'react-redux';
import Person from '@mui/icons-material/Person';
import Lock from '@mui/icons-material/Lock';
import Email from '@mui/icons-material/Email';
import ContentCopy from '@mui/icons-material/ContentCopy';
import CameraAlt from '@mui/icons-material/CameraAlt';
import Refresh from '@mui/icons-material/Refresh';
import type { RootState } from '../store';
import ChangePasswordModal from '../features/account/ChangePasswordModal';
import { ordersApi } from '../api/orders';
import Inventory2 from '@mui/icons-material/Inventory2';
import CheckCircle from '@mui/icons-material/CheckCircle';
import Today from '@mui/icons-material/Today';
import Store from '@mui/icons-material/Store';

function ProfileRow({
  icon,
  label,
  value,
  onClick,
  divider = true,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  onClick?: () => void;
  divider?: boolean;
}) {
  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, py: 1.5 }}>
        <Box sx={{ color: 'action.active', display: 'flex', alignItems: 'center' }}>{icon}</Box>
        <Typography variant="body2" color="text.secondary" sx={{ minWidth: 140 }}>
          {label}
        </Typography>
        {onClick ? (
          <Link
            component="button"
            variant="body2"
            onClick={onClick}
            sx={{ cursor: 'pointer', textDecoration: 'none', '&:hover': { textDecoration: 'underline' } }}
          >
            {value}
          </Link>
        ) : (
          <Typography variant="body2">{value}</Typography>
        )}
      </Box>
      {divider && <Divider />}
    </Box>
  );
}

const AVATAR_STORAGE_KEY = 'fbs_user_avatar';

function resizeImageToDataUrl(file: File, maxSize = 200): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const canvas = document.createElement('canvas');
      let { width, height } = img;
      if (width > maxSize || height > maxSize) {
        const ratio = Math.min(maxSize / width, maxSize / height);
        width = Math.round(width * ratio);
        height = Math.round(height * ratio);
      }
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('Canvas not supported'));
        return;
      }
      ctx.drawImage(img, 0, 0, width, height);
      resolve(canvas.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Failed to load image'));
    };
    img.src = url;
  });
}

export default function AccountPage() {
  const user = useSelector((state: RootState) => state.auth.user);
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['orders-stats'],
    queryFn: () => ordersApi.getStats(),
  });

  useEffect(() => {
    if (user?.id) {
      const stored = localStorage.getItem(`${AVATAR_STORAGE_KEY}_${user.id}`);
      setAvatarUrl(stored);
    }
  }, [user?.id]);

  const userCode = user?.id ? `U${String(user.id).padStart(5, '0')}` : '—';

  const handleCopyCode = () => {
    if (userCode !== '—') {
      navigator.clipboard.writeText(userCode);
    }
  };

  const handleAvatarClick = () => fileInputRef.current?.click();

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !file.type.startsWith('image/') || !user?.id) return;
    e.target.value = '';
    try {
      const dataUrl = await resizeImageToDataUrl(file);
      const key = `${AVATAR_STORAGE_KEY}_${user.id}`;
      localStorage.setItem(key, dataUrl);
      setAvatarUrl(dataUrl);
    } catch {
      // ignore
    }
  };

  return (
    <Box>
      <Typography variant="h4" fontWeight={600} sx={{ mb: 2 }}>
        Настройки пользователя
      </Typography>

      <Card
        sx={{
          borderTop: 4,
          borderTopColor: 'primary.main',
          mb: 3,
        }}
      >
        <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
          <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, p: 3 }}>
            {/* Левая часть: аватар, имя, код */}
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                pr: { md: 4 },
                mr: { md: 3 },
                borderRight: { md: 1 },
                borderColor: { md: 'divider' },
                minWidth: { md: 200 },
              }}
            >
              <Box sx={{ position: 'relative' }}>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleAvatarChange}
                  style={{ display: 'none' }}
                />
                <Avatar
                  src={avatarUrl ?? undefined}
                  sx={{
                    width: 100,
                    height: 100,
                    bgcolor: avatarUrl ? 'transparent' : 'grey.200',
                    color: 'grey.500',
                  }}
                >
                  {!avatarUrl && (user?.full_name?.charAt(0) ?? '?')}
                </Avatar>
                <IconButton
                  size="small"
                  onClick={handleAvatarClick}
                  sx={{
                    position: 'absolute',
                    bottom: -4,
                    right: -4,
                    bgcolor: 'grey.100',
                    '&:hover': { bgcolor: 'grey.200' },
                  }}
                >
                  <CameraAlt fontSize="small" sx={{ color: 'grey.600' }} />
                </IconButton>
              </Box>
              <Typography variant="h6" fontWeight={600} sx={{ mt: 2 }}>
                {user?.full_name ?? '—'}
              </Typography>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  Код:
                </Typography>
                <Typography
                  variant="body2"
                  fontWeight={500}
                  sx={{ color: 'primary.main', fontFamily: 'monospace' }}
                >
                  {userCode}
                </Typography>
                <IconButton size="small" onClick={handleCopyCode} sx={{ p: 0.25 }}>
                  <ContentCopy fontSize="small" sx={{ color: 'grey.600' }} />
                </IconButton>
                <IconButton size="small" sx={{ p: 0.25 }}>
                  <Refresh fontSize="small" sx={{ color: 'grey.600' }} />
                </IconButton>
              </Box>
            </Box>

            {/* Правая часть: список полей */}
            <Box sx={{ flex: 1, minWidth: 0 }}>
              <ProfileRow
                icon={<Person fontSize="small" />}
                label="Имя [Фамилия]"
                value={user?.full_name ?? '—'}
              />
              <ProfileRow
                icon={<Lock fontSize="small" />}
                label="Пароль"
                value="изменить пароль"
                onClick={() => setPasswordModalOpen(true)}
              />
              <ProfileRow
                icon={<Email fontSize="small" />}
                label="e-Mail"
                value={user?.email ?? 'e-mail не указан'}
                divider={false}
              />
            </Box>
          </Box>
        </CardContent>
      </Card>

      {/* Статистика под карточкой */}
      <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 1.5 }}>
        Общая статистика по заказам
      </Typography>
      {statsLoading ? (
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} variant="rounded" width={140} height={80} />
          ))}
        </Box>
      ) : stats ? (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2 }}>
            <Card variant="outlined" sx={{ minWidth: 120 }}>
              <CardContent sx={{ '&:last-child': { pb: 1.5 } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Inventory2 fontSize="small" color="action" />
                  <Typography variant="caption" color="text.secondary">
                    Всего
                  </Typography>
                </Box>
                <Typography variant="h5" fontWeight={600}>
                  {stats.total}
                </Typography>
              </CardContent>
            </Card>
            <Card variant="outlined" sx={{ minWidth: 120 }}>
              <CardContent sx={{ '&:last-child': { pb: 1.5 } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Inventory2 fontSize="small" color="primary" />
                  <Typography variant="caption" color="text.secondary">
                    На сборке
                  </Typography>
                </Box>
                <Typography variant="h5" fontWeight={600} color="primary.main">
                  {stats.on_assembly}
                </Typography>
              </CardContent>
            </Card>
            <Card variant="outlined" sx={{ minWidth: 120 }}>
              <CardContent sx={{ '&:last-child': { pb: 1.5 } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <CheckCircle fontSize="small" color="success" />
                  <Typography variant="caption" color="text.secondary">
                    Собрано
                  </Typography>
                </Box>
                <Typography variant="h5" fontWeight={600} color="success.main">
                  {stats.completed}
                </Typography>
              </CardContent>
            </Card>
            <Card variant="outlined" sx={{ minWidth: 120 }}>
              <CardContent sx={{ '&:last-child': { pb: 1.5 } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
                  <Today fontSize="small" color="action" />
                  <Typography variant="caption" color="text.secondary">
                    Сегодня
                  </Typography>
                </Box>
                <Typography variant="h5" fontWeight={600}>
                  {stats.completed_today}
                </Typography>
              </CardContent>
            </Card>
          </Box>
          {stats.by_marketplace.length > 0 && (
            <Box>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                По маркетплейсам
              </Typography>
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                {stats.by_marketplace.map((mp) => (
                  <Chip
                    key={mp.marketplace_id}
                    icon={<Store fontSize="small" />}
                    label={`${mp.name}: ${mp.completed}/${mp.total}`}
                    size="small"
                    variant="outlined"
                  />
                ))}
              </Box>
            </Box>
          )}
        </Box>
      ) : null}

      {passwordModalOpen && (
        <ChangePasswordModal onClose={() => setPasswordModalOpen(false)} />
      )}
    </Box>
  );
}
