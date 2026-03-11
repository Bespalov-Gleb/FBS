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
  Divider,
} from '@mui/material';
import LocalPrintshop from '@mui/icons-material/LocalPrintshop';
import { printSettingsApi } from '../api/printSettings';
import LoadingSpinner from '../components/common/LoadingSpinner';

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <Typography variant="subtitle1" fontWeight={600} sx={{ mt: 1, mb: 0.5 }}>
      {children}
    </Typography>
  );
}

export default function PrintSettingsPage() {
  const queryClient = useQueryClient();
  const [defaultPrinter, setDefaultPrinter] = useState('');
  const [labelFormat, setLabelFormat] = useState<'58mm' | '80mm'>('58mm');
  const [printerDpi, setPrinterDpi] = useState<203 | 300>(203);

  // Ozon ФБС этикетка
  const [ozonWidth, setOzonWidth] = useState(58);
  const [ozonHeight, setOzonHeight] = useState(40);
  const [ozonRotate, setOzonRotate] = useState(0);

  // WB ФБС стикер
  const [wbWidth, setWbWidth] = useState(58);
  const [wbHeight, setWbHeight] = useState(40);
  const [wbRotate, setWbRotate] = useState(0);

  // Штрихкоды товаров
  const [barcodeRotate, setBarcodeRotate] = useState(0);

  // КИЗ
  const [kizWidth, setKizWidth] = useState(40);
  const [kizHeight, setKizHeight] = useState(35);
  const [kizRotate, setKizRotate] = useState(0);

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
      setPrinterDpi((settings.printer_dpi === 300 ? 300 : 203) as 203 | 300);
      setOzonWidth(settings.ozon_labels?.width_mm ?? 58);
      setOzonHeight(settings.ozon_labels?.height_mm ?? 40);
      setOzonRotate(settings.ozon_labels?.rotate ?? 0);
      setWbWidth(settings.wb_labels?.width_mm ?? 58);
      setWbHeight(settings.wb_labels?.height_mm ?? 40);
      setWbRotate(settings.wb_labels?.rotate ?? 0);
      setBarcodeRotate(settings.barcode_labels?.rotate ?? 0);
      setKizWidth(settings.kiz_labels?.width_mm ?? 40);
      setKizHeight(settings.kiz_labels?.height_mm ?? 35);
      setKizRotate(settings.kiz_labels?.rotate ?? 0);
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
        printer_dpi: printerDpi,
        ozon_labels: { width_mm: ozonWidth, height_mm: ozonHeight, rotate: ozonRotate },
        wb_labels: { width_mm: wbWidth, height_mm: wbHeight, rotate: wbRotate },
        barcode_labels: { rotate: barcodeRotate },
        kiz_labels: { width_mm: kizWidth, height_mm: kizHeight, rotate: kizRotate },
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

  const rotateSelect = (value: number, onChange: (v: number) => void) => (
    <FormControl size="small" sx={{ flex: 1, minWidth: 130 }}>
      <InputLabel>Поворот</InputLabel>
      <Select
        value={value}
        label="Поворот"
        onChange={(e) => onChange(Number(e.target.value))}
      >
        <MenuItem value={0}>0° (без поворота)</MenuItem>
        <MenuItem value={90}>90° по часовой</MenuItem>
        <MenuItem value={180}>180°</MenuItem>
        <MenuItem value={270}>270° (против часовой)</MenuItem>
      </Select>
    </FormControl>
  );

  const sizeField = (
    label: string,
    value: number,
    onChange: (v: number) => void,
    min = 30,
    max = 120,
    defaultVal = 58,
  ) => (
    <TextField
      type="number"
      label={label}
      value={value}
      onChange={(e) => onChange(Math.max(min, Math.min(max, parseInt(e.target.value, 10) || defaultVal)))}
      inputProps={{ min, max }}
      size="small"
      sx={{ flex: 1 }}
    />
  );

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

              {/* ── Принтер ── */}
              <SectionTitle>Принтер</SectionTitle>
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
                      <MenuItem key={p} value={p}>{p}</MenuItem>
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

              <FormControl fullWidth size="small" sx={{ mt: 1 }}>
                <InputLabel>DPI принтера</InputLabel>
                <Select
                  value={printerDpi}
                  label="DPI принтера"
                  onChange={(e) => setPrinterDpi(Number(e.target.value) as 203 | 300)}
                >
                  <MenuItem value={203}>203 DPI</MenuItem>
                  <MenuItem value={300}>300 DPI</MenuItem>
                </Select>
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                  Типичные значения для термо-принтеров. 203 — чаще всего. 300 — для высокого разрешения.
                </Typography>
              </FormControl>

              <Divider />

              {/* ── ФБС этикетка Ozon ── */}
              <SectionTitle>ФБС этикетка Ozon</SectionTitle>
              <Typography variant="caption" color="text.secondary">
                Этикетка отправления, которую Ozon возвращает в PDF. Размер и поворот для вашего принтера.
              </Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {sizeField('Ширина (мм)', ozonWidth, setOzonWidth, 40, 120, 58)}
                {sizeField('Высота (мм)', ozonHeight, setOzonHeight, 30, 120, 40)}
                {rotateSelect(ozonRotate, setOzonRotate)}
              </Box>

              <Divider />

              {/* ── ФБС стикер Wildberries ── */}
              <SectionTitle>ФБС стикер Wildberries</SectionTitle>
              <Typography variant="caption" color="text.secondary">
                PNG-стикер WB, конвертируется в PDF. Укажите размер и поворот для вашего принтера.
              </Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {sizeField('Ширина (мм)', wbWidth, setWbWidth, 40, 120, 58)}
                {sizeField('Высота (мм)', wbHeight, setWbHeight, 30, 120, 40)}
                {rotateSelect(wbRotate, setWbRotate)}
              </Box>

              <Divider />

              {/* ── Штрихкоды товаров ── */}
              <SectionTitle>Штрихкоды товаров</SectionTitle>
              <Typography variant="caption" color="text.secondary">
                Штрихкоды Ozon (OZN+SKU) и WB (EAN13). Ширина и поворот — общие для обоих.
              </Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                <FormControl size="small" sx={{ flex: 1, minWidth: 130 }}>
                  <InputLabel>Ширина этикетки</InputLabel>
                  <Select
                    value={labelFormat}
                    label="Ширина этикетки"
                    onChange={(e) => setLabelFormat(e.target.value as '58mm' | '80mm')}
                  >
                    <MenuItem value="58mm">58 мм</MenuItem>
                    <MenuItem value="80mm">80 мм</MenuItem>
                  </Select>
                </FormControl>
                {rotateSelect(barcodeRotate, setBarcodeRotate)}
              </Box>

              <Divider />

              {/* ── КИЗ ── */}
              <SectionTitle>Этикетка КИЗ (DataMatrix)</SectionTitle>
              <Typography variant="caption" color="text.secondary">
                Дубль КИЗ — DataMatrix + 31 символ кода. По умолчанию 40×35 мм.
              </Typography>
              <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                {sizeField('Ширина (мм)', kizWidth, setKizWidth, 20, 100, 40)}
                {sizeField('Высота (мм)', kizHeight, setKizHeight, 20, 100, 35)}
                {rotateSelect(kizRotate, setKizRotate)}
              </Box>

              <Divider />

              {/* ── Автоматизация ── */}
              <SectionTitle>Автоматизация</SectionTitle>
              <FormControlLabel
                control={<Switch checked={autoPrint} onChange={(e) => setAutoPrint(e.target.checked)} />}
                label="Автопечать этикеток при клике на артикул"
              />
              <FormControlLabel
                control={<Switch checked={autoPrintKiz} onChange={(e) => setAutoPrintKiz(e.target.checked)} />}
                label="Автопечать дубля КИЗ после скана"
              />

              <Divider />

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
