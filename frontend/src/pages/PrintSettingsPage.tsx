import { useState, useEffect } from 'react';
import { isPrintAgentAvailable, printViaAgent, getPrintAgentPrinters } from '../api/printAgent';
import { openBlobInNewWindow } from '../utils/printUtils';
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
  const [ozonWidth, setOzonWidth] = useState(58);
  const [ozonHeight, setOzonHeight] = useState(40);
  const [wbWidth, setWbWidth] = useState(58);
  const [wbHeight, setWbHeight] = useState(40);
  const [autoPrint, setAutoPrint] = useState(true);
  const [autoPrintKiz, setAutoPrintKiz] = useState(true);
  const [agentAvailable, setAgentAvailable] = useState(false);
  const [agentPrinters, setAgentPrinters] = useState<string[]>([]);
  const [testPrinting, setTestPrinting] = useState(false);
  const [testPrintError, setTestPrintError] = useState<string | null>(null);

  const { data: settings, isLoading } = useQuery({
    queryKey: ['print-settings'],
    queryFn: () => printSettingsApi.get(),
  });

  useEffect(() => {
    if (settings) {
      setDefaultPrinter(settings.default_printer ?? '');
      setLabelFormat((settings.label_format as '58mm' | '80mm') ?? '58mm');
      setOzonWidth(settings.ozon_labels?.width_mm ?? 58);
      setOzonHeight(settings.ozon_labels?.height_mm ?? 40);
      setWbWidth(settings.wb_labels?.width_mm ?? 58);
      setWbHeight(settings.wb_labels?.height_mm ?? 40);
      setAutoPrint(settings.auto_print_on_click !== false);
      setAutoPrintKiz(settings.auto_print_kiz_duplicate !== false);
    }
  }, [settings]);

  const checkAgent = () => {
    isPrintAgentAvailable().then((ok) => {
      setAgentAvailable(ok);
      if (ok) getPrintAgentPrinters().then(setAgentPrinters);
    });
  };

  useEffect(() => {
    checkAgent();
  }, []);

  const updateMutation = useMutation({
    mutationFn: () =>
      printSettingsApi.update({
        default_printer: defaultPrinter,
        label_format: labelFormat,
        ozon_labels: { width_mm: ozonWidth, height_mm: ozonHeight },
        wb_labels: { width_mm: wbWidth, height_mm: wbHeight },
        auto_print_on_click: autoPrint,
        auto_print_kiz_duplicate: autoPrintKiz,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['print-settings'] }),
  });

  const handleSave = () => updateMutation.mutate();

  const handleTestPrint = async () => {
    setTestPrintError(null);
    setTestPrinting(true);
    try {
      const blob = await printSettingsApi.getTestLabelBlob();
      if (agentAvailable) {
        const ok = await printViaAgent(blob, defaultPrinter || undefined, 'noscale');
        if (!ok) {
          setTestPrintError('Агент не ответил или печать не удалась. Проверьте, что агент запущен и SumatraPDF установлен.');
        }
      } else {
        openBlobInNewWindow(blob, { triggerPrint: true });
      }
    } catch (e) {
      setTestPrintError(e instanceof Error ? e.message : 'Ошибка при печати');
    } finally {
      setTestPrinting(false);
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

      <Alert
        severity={agentAvailable ? 'success' : 'info'}
        sx={{ mb: 2 }}
        action={
          !agentAvailable && (
            <Button color="inherit" size="small" onClick={checkAgent}>
              Проверить снова
            </Button>
          )
        }
      >
        {agentAvailable
          ? 'Агент печати подключен. Тихая печать без диалога.'
          : 'Печать выполняется через браузер. При первой печати выберите принтер в диалоге. Установите fbs-print-agent для тихой печати.'}
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
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                  Ширина для штрихкодов Ozon и WB (58 или 80 мм)
                </Typography>
              </FormControl>
              <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2 }}>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                    Размер этикеток Ozon (мм)
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <TextField
                      type="number"
                      label="Ширина"
                      value={ozonWidth}
                      onChange={(e) => setOzonWidth(Math.max(40, Math.min(120, parseInt(e.target.value, 10) || 58)))}
                      inputProps={{ min: 40, max: 120 }}
                      size="small"
                      sx={{ flex: 1 }}
                    />
                    <TextField
                      type="number"
                      label="Высота"
                      value={ozonHeight}
                      onChange={(e) => setOzonHeight(Math.max(30, Math.min(120, parseInt(e.target.value, 10) || 40)))}
                      inputProps={{ min: 30, max: 120 }}
                      size="small"
                      sx={{ flex: 1 }}
                    />
                  </Box>
                </Box>
                <Box>
                  <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                    Размер этикеток Wildberries (мм)
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <TextField
                      type="number"
                      label="Ширина"
                      value={wbWidth}
                      onChange={(e) => setWbWidth(Math.max(40, Math.min(120, parseInt(e.target.value, 10) || 58)))}
                      inputProps={{ min: 40, max: 120 }}
                      size="small"
                      sx={{ flex: 1 }}
                    />
                    <TextField
                      type="number"
                      label="Высота"
                      value={wbHeight}
                      onChange={(e) => setWbHeight(Math.max(30, Math.min(120, parseInt(e.target.value, 10) || 40)))}
                      inputProps={{ min: 30, max: 120 }}
                      size="small"
                      sx={{ flex: 1 }}
                    />
                  </Box>
                </Box>
              </Box>
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
              {agentAvailable && agentPrinters.length > 0 ? (
                <FormControl fullWidth size="small">
                  <InputLabel>Принтер</InputLabel>
                  <Select
                    value={defaultPrinter}
                    label="Принтер"
                    onChange={(e) => setDefaultPrinter(e.target.value)}
                  >
                    <MenuItem value="">По умолчанию</MenuItem>
                    {agentPrinters.map((p) => (
                      <MenuItem key={p} value={p}>
                        {p}
                      </MenuItem>
                    ))}
                  </Select>
                  <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                    Агент печати использует выбранный принтер
                  </Typography>
                </FormControl>
              ) : (
                <TextField
                  label="Принтер"
                  value={defaultPrinter || (agentAvailable ? 'По умолчанию' : 'Выберите в диалоге печати')}
                  fullWidth
                  InputProps={{ readOnly: true }}
                  size="small"
                  helperText={agentAvailable ? 'Агент использует системный принтер по умолчанию' : 'Браузер не может задать принтер. Выберите его при первой печати.'}
                />
              )}
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <Button variant="contained" onClick={handleSave} disabled={updateMutation.isPending}>
                  Сохранить
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<LocalPrintshop />}
                  onClick={handleTestPrint}
                  disabled={testPrinting}
                >
                  {testPrinting ? 'Печать…' : 'Тестовая печать'}
                </Button>
                {testPrintError && (
                  <Alert severity="error" sx={{ mt: 1 }} onClose={() => setTestPrintError(null)}>
                    {testPrintError}
                  </Alert>
                )}
              </Box>
            </Box>
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
