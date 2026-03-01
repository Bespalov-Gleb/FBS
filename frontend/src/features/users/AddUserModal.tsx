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
} from '@mui/material';
import type { UserCreate } from '../../api/users';

const schema = z.object({
  email: z.string().email('Некорректный email'),
  password: z.string().min(6, 'Минимум 6 символов'),
  full_name: z.string().min(1, 'Введите имя'),
  role: z.enum(['admin', 'packer']),
});

type FormData = z.infer<typeof schema>;

interface AddUserModalProps {
  onClose: () => void;
  onSubmit: (data: UserCreate) => void;
  isSubmitting: boolean;
}

export default function AddUserModal({ onClose, onSubmit, isSubmitting }: AddUserModalProps) {
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { email: '', password: '', full_name: '', role: 'packer' },
  });

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Добавить пользователя</DialogTitle>
      <form onSubmit={handleSubmit((data) => onSubmit(data))}>
        <DialogContent>
          <TextField
            {...register('email')}
            label="Email"
            type="email"
            fullWidth
            margin="normal"
            error={!!errors.email}
            helperText={errors.email?.message}
          />
          <TextField
            {...register('password')}
            label="Пароль"
            type="password"
            fullWidth
            margin="normal"
            error={!!errors.password}
            helperText={errors.password?.message}
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
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="contained" disabled={isSubmitting}>
            Добавить
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
