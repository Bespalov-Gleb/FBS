import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Typography,
} from '@mui/material';

const schema = z
  .object({
    current_password: z.string().min(1, 'Введите текущий пароль'),
    new_password: z.string().min(6, 'Минимум 6 символов'),
    confirm_password: z.string().min(1, 'Подтвердите пароль'),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: 'Пароли не совпадают',
    path: ['confirm_password'],
  });

type FormData = z.infer<typeof schema>;

interface ChangePasswordModalProps {
  onClose: () => void;
}

export default function ChangePasswordModal({ onClose }: ChangePasswordModalProps) {
  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      current_password: '',
      new_password: '',
      confirm_password: '',
    },
  });

  const onSubmit = async (_data: FormData) => {
    // Backend endpoint для смены пароля нужно добавить отдельно
    onClose();
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Изменить пароль</DialogTitle>
      <form onSubmit={handleSubmit(onSubmit)}>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Endpoint для смены пароля в backend нужно добавить отдельно.
          </Typography>
          <TextField
            {...register('current_password')}
            label="Текущий пароль"
            type="password"
            fullWidth
            margin="normal"
            error={!!errors.current_password}
            helperText={errors.current_password?.message}
          />
          <TextField
            {...register('new_password')}
            label="Новый пароль"
            type="password"
            fullWidth
            margin="normal"
            error={!!errors.new_password}
            helperText={errors.new_password?.message}
          />
          <TextField
            {...register('confirm_password')}
            label="Подтверждение пароля"
            type="password"
            fullWidth
            margin="normal"
            error={!!errors.confirm_password}
            helperText={errors.confirm_password?.message}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="contained">
            Сохранить
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
