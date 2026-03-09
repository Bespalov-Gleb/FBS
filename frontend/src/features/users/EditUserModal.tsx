import { useEffect, useState } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Checkbox,
  Divider,
  Typography,
  Box,
  Chip,
  Alert,
  Snackbar,
} from '@mui/material';
import { useQuery, useMutation } from '@tanstack/react-query';
import { usersApi } from '../../api/users';
import type { UserUpdate } from '../../api/users';
import { marketplacesApi } from '../../api/marketplaces';
import LoadingSpinner from '../../components/common/LoadingSpinner';

const schema = z.object({
  full_name: z.string().min(1, 'Введите имя'),
  role: z.enum(['admin', 'packer']),
  is_active: z.boolean(),
});

type FormData = z.infer<typeof schema>;

interface EditUserModalProps {
  userId: number;
  onClose: () => void;
  onSubmit: (data: UserUpdate) => void;
  isSubmitting: boolean;
}

export default function EditUserModal({
  userId,
  onClose,
  onSubmit,
  isSubmitting,
}: EditUserModalProps) {
  const [snackbar, setSnackbar] = useState<{ message: string; severity: 'success' | 'error' } | null>(null);

  const { data: user, isLoading } = useQuery({
    queryKey: ['user', userId],
    queryFn: () => usersApi.get(userId),
  });

  const { data: allMarketplaces = [] } = useQuery({
    queryKey: ['marketplaces'],
    queryFn: () => marketplacesApi.list(),
  });

  const { data: accessList = [], refetch: refetchAccess } = useQuery({
    queryKey: ['user-marketplace-access', userId],
    queryFn: () => usersApi.getMarketplaceAccess(userId),
  });

  const { data: stats } = useQuery({
    queryKey: ['user-stats', userId],
    queryFn: () => usersApi.getStats(userId),
  });

  const setAccessMutation = useMutation({
    mutationFn: (ids: number[]) => usersApi.setMarketplaceAccess(userId, ids),
    onSuccess: () => {
      refetchAccess();
      setSnackbar({ message: 'Доступ обновлён', severity: 'success' });
    },
    onError: () => setSnackbar({ message: 'Ошибка сохранения доступа', severity: 'error' }),
  });

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: '', role: 'packer', is_active: true },
  });

  useEffect(() => {
    if (user) {
      reset({
        full_name: user.full_name,
        role: user.role as 'admin' | 'packer',
        is_active: user.is_active,
      });
    }
  }, [user, reset]);

  const currentAccessIds = new Set(accessList.map((a) => a.marketplace_id));

  const handleToggleMarketplace = (mpId: number) => {
    const next = new Set(currentAccessIds);
    if (next.has(mpId)) {
      next.delete(mpId);
    } else {
      next.add(mpId);
    }
    setAccessMutation.mutate([...next]);
  };

  const isPacker = user?.role === 'packer';

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Редактировать пользователя</DialogTitle>
      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <form onSubmit={handleSubmit((data) => onSubmit(data))}>
          <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {/* ── Основные данные ── */}
            <TextField
              label="Email"
              value={user?.email ?? ''}
              fullWidth
              margin="normal"
              disabled
            />
            <TextField
              {...register('full_name')}
              label="Имя"
              fullWidth
              margin="normal"
              error={!!errors.full_name}
              helperText={errors.full_name?.message}
            />
            <FormControl fullWidth margin="normal">
              <InputLabel>Роль</InputLabel>
              <Controller
                name="role"
                control={control}
                render={({ field }) => (
                  <Select {...field} label="Роль">
                    <MenuItem value="packer">Упаковщик</MenuItem>
                    <MenuItem value="admin">Админ</MenuItem>
                  </Select>
                )}
              />
            </FormControl>
            <FormControlLabel
              control={<Checkbox {...register('is_active')} />}
              label="Активен"
              sx={{ mt: 1, mb: 1 }}
            />

            {/* ── Статистика упаковщика ── */}
            {isPacker && stats && (
              <>
                <Divider sx={{ my: 1.5 }} />
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Статистика
                </Typography>
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  <Chip
                    label={`За час: ${stats.orders_last_hour}`}
                    size="small"
                    variant="outlined"
                    color="primary"
                  />
                  <Chip
                    label={`Сегодня: ${stats.orders_today}`}
                    size="small"
                    variant="outlined"
                    color="primary"
                  />
                  <Chip
                    label={`Всего: ${stats.orders_total}`}
                    size="small"
                    variant="outlined"
                  />
                  {stats.avg_minutes_per_order !== null && (
                    <Chip
                      label={`~${stats.avg_minutes_per_order} мин/заказ`}
                      size="small"
                      variant="outlined"
                      color="secondary"
                    />
                  )}
                </Box>
              </>
            )}

            {/* ── Доступ к магазинам (только для упаковщиков) ── */}
            {isPacker && (
              <>
                <Divider sx={{ my: 1.5 }} />
                <Typography variant="subtitle2" color="text.secondary" gutterBottom>
                  Доступ к магазинам
                  <Typography component="span" variant="caption" sx={{ ml: 1 }}>
                    (без галочек — доступ ко всем)
                  </Typography>
                </Typography>
                {allMarketplaces.length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    Нет доступных магазинов
                  </Typography>
                ) : (
                  <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                    {allMarketplaces.map((mp) => (
                      <FormControlLabel
                        key={mp.id}
                        control={
                          <Checkbox
                            checked={currentAccessIds.has(mp.id)}
                            onChange={() => handleToggleMarketplace(mp.id)}
                            disabled={setAccessMutation.isPending}
                            size="small"
                          />
                        }
                        label={
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            <Typography variant="body2">{mp.name}</Typography>
                            <Chip
                              label={mp.type}
                              size="small"
                              sx={{ height: 18, fontSize: '0.65rem' }}
                              variant="outlined"
                            />
                          </Box>
                        }
                      />
                    ))}
                  </Box>
                )}
              </>
            )}

          </DialogContent>

          <DialogActions>
            <Button onClick={onClose}>Отмена</Button>
            <Button type="submit" variant="contained" disabled={isSubmitting}>
              Сохранить
            </Button>
          </DialogActions>
        </form>
      )}

      <Snackbar
        open={!!snackbar}
        autoHideDuration={3000}
        onClose={() => setSnackbar(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert onClose={() => setSnackbar(null)} severity={snackbar?.severity ?? 'success'}>
          {snackbar?.message}
        </Alert>
      </Snackbar>
    </Dialog>
  );
}
