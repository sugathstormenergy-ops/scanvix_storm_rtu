import { Link } from 'react-router-dom';
import { EmptyState } from '../components/ui/EmptyState';

export default function NotFoundPage() {
  return (
    <div className="content" data-testid="page-not-found">
      <div className="card auto">
        <EmptyState icon="fa-compass" title="Page not found">
          <Link to="/" className="meter-link">Go to the Overview</Link>
        </EmptyState>
      </div>
    </div>
  );
}
