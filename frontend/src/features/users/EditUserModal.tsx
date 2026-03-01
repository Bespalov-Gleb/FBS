import { useEffect } from 'react';
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
} from '@mui/material';
import { useQuery } from '@tanstack/react-query';
import { usersApi } from '../../api/users';
import type { UserUpdate } from '../../api/users';
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
  const { data: user, isLoading } = useQuery({
    queryKey: ['user', userId],
    queryFn: () => usersApi.get(userId),
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

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Редактировать пользователя</DialogTitle>
      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <form onSubmit={handleSubmit((data) => onSubmit(data))}>
          <DialogContent>
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
              sx={{ mt: 1, display: 'block' }}
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose}>Отмена</Button>
            <Button type="submit" variant="contained" disabled={isSubmitting}>
              Сохранить
            </Button>
          </DialogActions>
        </form>
      )}
    </Dialog>
  );
}
