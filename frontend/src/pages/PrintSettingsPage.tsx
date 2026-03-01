import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Box,
  Typography,
  Card,
  CardContent,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Switch,
  Button,
  Alert,
} from '@mui/material';
import LocalPrintshop from '@mui/icons-material/LocalPrintshop';
import { printSettingsApi } from '../api/printSettings';
import LoadingSpinner from '../components/common/LoadingSpinner';

export default function PrintSettingsPage() {
  const queryClient = useQueryClient();
  const [defaultPrinter, setDefaultPrinter] = useState('');
  const [labelFormat, setLabelFormat] = useState<'58mm' | '80mm'>('58mm');
  const [autoPrint, setAutoPrint] = useState(true);
  const [autoPrintKiz, setAutoPrintKiz] = useState(true);

  const { data: settings, isLoading } = useQuery({
    queryKey: ['print-settings'],
    queryFn: () => printSettingsApi.get(),
  });

  useEffect(() => {
    if (settings) {
      setDefaultPrinter(settings.default_printer ?? '');
      setLabelFormat((settings.label_format as '58mm' | '80mm') ?? '58mm');
      setAutoPrint(settings.auto_print_on_click !== false);
      setAutoPrintKiz(settings.auto_print_kiz_duplicate !== false);
    }
  }, [settings]);

  const updateMutation = useMutation({
    mutationFn: () =>
      printSettingsApi.update({
        default_printer: defaultPrinter,
        label_format: labelFormat,
        auto_print_on_click: autoPrint,
        auto_print_kiz_duplicate: autoPrintKiz,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['print-settings'] }),
  });

  const handleSave = () => updateMutation.mutate();

  const handleTestPrint = async () => {
    try {
      const blob = await printSettingsApi.getTestLabelBlob();
      const url = URL.createObjectURL(blob);
      const win = window.open(url, '_blank');
      if (win) {
        win.onload = () => win.print();
      } else {
        window.location.href = url;
      }
    } catch {
      window.print();
    }
  };

  return (
    <Box>
      <Typography variant="h4" fontWeight={600} gutterBottom>
        Диспетчер печати
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Настройки печати этикеток через браузер
      </Typography>

      <Alert severity="info" sx={{ mb: 2 }}>
        Печать выполняется через браузер. При первой печати выберите принтер в диалоге.
        Термопринтер должен быть установлен как обычный принтер в системе.
      </Alert>

      {isLoading ? (
        <LoadingSpinner />
      ) : (
        <Card>
          <CardContent>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <FormControl fullWidth>
                <InputLabel>Формат этикеток</InputLabel>
                <Select
                  value={labelFormat}
                  label="Формат этикеток"
                  onChange={(e) => setLabelFormat(e.target.value as '58mm' | '80mm')}
                >
                  <MenuItem value="58mm">58 мм</MenuItem>
                  <MenuItem value="80mm">80 мм</MenuItem>
                </Select>
              </FormControl>
              <FormControlLabel
                control={
                  <Switch checked={autoPrint} onChange={(e) => setAutoPrint(e.target.checked)} />
                }
                label="Автопечать 2 этикеток при клике на артикул"
              />
              <FormControlLabel
                control={
                  <Switch checked={autoPrintKiz} onChange={(e) => setAutoPrintKiz(e.target.checked)} />
                }
                label="Автопечать дубля КИЗ после скана"
              />
              <TextField
                label="Принтер"
                value={defaultPrinter || 'Выберите в диалоге печати'}
                fullWidth
                InputProps={{ readOnly: true }}
                size="small"
                helperText="Браузер не может задать принтер. Выберите его при первой печати."
              />
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Button variant="contained" onClick={handleSave} disabled={updateMutation.isPending}>
                  Сохранить
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<LocalPrintshop />}
                  onClick={handleTestPrint}
                >
                  Тестовая печать
                </Button>
              </Box>
            </Box>
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
