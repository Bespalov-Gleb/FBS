import { useState } from 'react';
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
  FormControlLabel,
  Checkbox,
  Typography,
} from '@mui/material';
import { marketplacesApi, type MarketplaceCreate } from '../../api/marketplaces';

const schema = z.object({
  name: z.string().min(1, 'Введите название'),
  api_key: z.string().min(1, 'Введите API ключ'),
  client_id: z.string().optional(),
  is_kiz_enabled: z.boolean().optional(),
  save_kiz_to_file: z.boolean().optional(),
});

type FormData = z.infer<typeof schema>;

interface AddMarketplaceModalProps {
  type: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function AddMarketplaceModal({ type, onClose, onSuccess }: AddMarketplaceModalProps) {
  const [error, setError] = useState<string | null>(null);

  const isOzon = type === 'ozon';

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      api_key: '',
      client_id: '',
      is_kiz_enabled: false,
      save_kiz_to_file: false,
    },
  });

  const onSubmit = async (data: FormData) => {
    setError(null);
    try {
      const payload: MarketplaceCreate = {
        type,
        name: data.name,
        api_key: data.api_key,
        is_kiz_enabled: data.is_kiz_enabled ?? false,
        save_kiz_to_file: data.save_kiz_to_file ?? false,
      };
      if (isOzon) {
        payload.client_id = data.client_id || undefined;
      }
      await marketplacesApi.create(payload);
      onSuccess();
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        : null;
      setError(Array.isArray(msg) ? msg[0] : (msg ?? 'Ошибка подключения'));
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Подключить {type === 'ozon' ? 'Ozon' : 'Wildberries'}</DialogTitle>
      <form onSubmit={handleSubmit(onSubmit)}>
        <DialogContent>
          <TextField
            {...register('name')}
            label="Название аккаунта"
            fullWidth
            margin="normal"
            error={!!errors.name}
            helperText={errors.name?.message}
          />
          <TextField
            {...register('api_key')}
            label="API ключ"
            type="password"
            fullWidth
            margin="normal"
            error={!!errors.api_key}
            helperText={errors.api_key?.message}
          />
          {isOzon && (
            <TextField
              {...register('client_id')}
              label="Client ID (Ozon)"
              fullWidth
              margin="normal"
            />
          )}
          <FormControlLabel
            control={<Checkbox {...register('is_kiz_enabled')} />}
            label="Режим КИЗ (WB + Ozon)"
            sx={{ mt: 1, display: 'block' }}
          />
          <FormControlLabel
            control={<Checkbox {...register('save_kiz_to_file')} />}
            label="Сохранять КИЗ в файл после упаковки"
            sx={{ mt: 0.5, display: 'block' }}
          />
          {error && (
            <Typography color="error" variant="body2" sx={{ mt: 1 }}>
              {error}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Отмена</Button>
          <Button type="submit" variant="contained" disabled={isSubmitting}>
            Подключить
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
