import { useState, useEffect } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  FormControlLabel,
  Switch,
  Box,
  Typography,
} from '@mui/material';
import Sync from '@mui/icons-material/Sync';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { marketplacesApi } from '../../api/marketplaces';
import { warehousesApi } from '../../api/warehouses';
import LoadingSpinner from '../../components/common/LoadingSpinner';

interface MarketplaceSettingsModalProps {
  marketplaceId: number;
  onClose: () => void;
  onSyncOrders: () => void;
}

export default function MarketplaceSettingsModal({
  marketplaceId,
  onClose,
  onSyncOrders,
}: MarketplaceSettingsModalProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [isKizEnabled, setIsKizEnabled] = useState(false);
  const [saveKizToFile, setSaveKizToFile] = useState(false);

  const { data: marketplace, isLoading } = useQuery({
    queryKey: ['marketplace', marketplaceId],
    queryFn: () => marketplacesApi.get(marketplaceId),
  });

  useEffect(() => {
    if (marketplace) {
      setName(marketplace.name);
      setIsKizEnabled(marketplace.is_kiz_enabled ?? false);
      setSaveKizToFile(marketplace.save_kiz_to_file ?? false);
    }
  }, [marketplace]);

  const { data: warehouses = [], isLoading: warehousesLoading } = useQuery({
    queryKey: ['warehouses', marketplaceId],
    queryFn: () => warehousesApi.listByMarketplace(marketplaceId),
  });

  const [warehouseColors, setWarehouseColors] = useState<Record<number, string>>({});

  useEffect(() => {
    if (warehouses.length) {
      const colors: Record<number, string> = {};
      warehouses.forEach((w) => {
        colors[w.id] = w.color || '#4a5568';
      });
      setWarehouseColors((prev) => ({ ...colors, ...prev }));
    }
  }, [warehouses]);

  const updateMutation = useMutation({
    mutationFn: () =>
      marketplacesApi.update(marketplaceId, { name, is_kiz_enabled: isKizEnabled, save_kiz_to_file: saveKizToFile }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['marketplaces', 'marketplace'] }),
  });

  const syncWarehousesMutation = useMutation({
    mutationFn: () => warehousesApi.sync(marketplaceId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['warehouses', marketplaceId] }),
  });

  const testMutation = useMutation({
    mutationFn: () => marketplacesApi.test(marketplaceId),
  });

  const updateColorMutation = useMutation({
    mutationFn: ({ id, color }: { id: number; color: string }) =>
      warehousesApi.updateColor(id, color),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['warehouses', marketplaceId] }),
  });

  const handleSave = () => {
    updateMutation.mutate(undefined, { onSuccess: onClose });
  };

  const handleColorChange = (warehouseId: number, color: string) => {
    setWarehouseColors((prev) => ({ ...prev, [warehouseId]: color }));
  };

  const handleColorBlur = (warehouseId: number) => {
    const color = warehouseColors[warehouseId];
    if (color && /^#[0-9A-Fa-f]{6}$/.test(color)) {
      updateColorMutation.mutate({ id: warehouseId, color });
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Настройки маркетплейса</DialogTitle>
      <DialogContent>
        {isLoading ? (
          <LoadingSpinner />
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Название"
              value={name}
              onChange={(e) => setName(e.target.value)}
              fullWidth
            />
            <FormControlLabel
              control={
                <Switch checked={isKizEnabled} onChange={(e) => setIsKizEnabled(e.target.checked)} />
              }
              label="Режим КИЗ"
            />
            <FormControlLabel
              control={
                <Switch checked={saveKizToFile} onChange={(e) => setSaveKizToFile(e.target.checked)} />
              }
              label="Сохранять КИЗ в файл после упаковки"
            />
            <Typography variant="subtitle2">Склады</Typography>
            {warehousesLoading ? (
              <LoadingSpinner />
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                {warehouses.map((w) => (
                  <Box key={w.id} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <TextField
                      size="small"
                      label="Цвет (HEX)"
                      value={warehouseColors[w.id] ?? '#4a5568'}
                      onChange={(e) => handleColorChange(w.id, e.target.value)}
                      onBlur={() => handleColorBlur(w.id)}
                      sx={{ width: 120 }}
                      placeholder="#FF5733"
                    />
                    <Typography variant="body2">{w.name}</Typography>
                  </Box>
                ))}
              </Box>
            )}
            <Button
              startIcon={<Sync />}
              onClick={() => syncWarehousesMutation.mutate()}
              disabled={syncWarehousesMutation.isPending}
            >
              Синхронизировать склады
            </Button>
            <Button
              variant="outlined"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending}
            >
              {testMutation.data?.success ? 'Подключение OK' : 'Тест подключения'}
            </Button>
            <Button variant="outlined" onClick={onSyncOrders}>
              Синхронизировать заказы
            </Button>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Закрыть</Button>
        <Button variant="contained" onClick={handleSave} disabled={updateMutation.isPending}>
          Сохранить
        </Button>
      </DialogActions>
    </Dialog>
  );
}
