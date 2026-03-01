import { Link, useLocation } from 'react-router-dom';
import MuiBreadcrumbs from '@mui/material/Breadcrumbs';
import Typography from '@mui/material/Typography';

interface BreadcrumbItem {
  label: string;
  path: string;
}

interface BreadcrumbsProps {
  items: BreadcrumbItem[];
}

const sectionLabels: Record<string, string> = {
  assembly: 'Настройки',
  account: 'Настройки',
  marketplaces: 'Настройки',
  'print-settings': 'Настройки',
  users: 'Администрирование',
};

export default function Breadcrumbs({ items }: BreadcrumbsProps) {
  const location = useLocation();
  const firstSeg = location.pathname.split('/').filter(Boolean)[0];
  const sectionLabel = firstSeg ? sectionLabels[firstSeg] : null;

  const allItems = sectionLabel
    ? [{ label: sectionLabel, path: '' }, ...items]
    : items;

  return (
    <MuiBreadcrumbs aria-label="breadcrumb" sx={{ '& .MuiBreadcrumbs-separator': { mx: 0.5 } }}>
      {allItems.map((item, idx) =>
        idx < allItems.length - 1 && item.path ? (
          <Link
            key={item.path}
            to={item.path}
            style={{
              color: 'inherit',
              textDecoration: 'none',
              fontSize: '0.875rem',
            }}
          >
            {item.label}
          </Link>
        ) : (
          <Typography key={item.path || idx} variant="body2" color="text.secondary">
            {item.label}
          </Typography>
        ),
      )}
    </MuiBreadcrumbs>
  );
}
