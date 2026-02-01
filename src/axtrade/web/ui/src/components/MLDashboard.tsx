import { useState } from 'react';
import {
    Brain,
    TrendingUp,
    TrendingDown,
    Minus,
    Activity,
    Trash2,
    Plus,
    RefreshCw,
    Target,
    BarChart2,
} from 'lucide-react';
import { useMLModels, useMLSummary, useMLPredictions, useDeleteModel, useCreateModel } from '../hooks/useML';
import type { MLModel, MLPrediction, CreateModelRequest, PredictionDirection } from '../types/ml';
import { DIRECTION_COLORS, MODEL_TYPE_LABELS } from '../types/ml';

const MLDashboard = () => {
    const { models, loading: modelsLoading, refetch: refetchModels } = useMLModels();
    const { summary, loading: summaryLoading } = useMLSummary();
    const { deleteModel } = useDeleteModel();
    const { createModel, loading: createLoading } = useCreateModel();

    const [selectedSymbol, setSelectedSymbol] = useState<string>('');
    const [showCreateModal, setShowCreateModal] = useState(false);

    const handleDelete = async (modelId: string) => {
        if (confirm('Are you sure you want to delete this model?')) {
            await deleteModel(modelId);
            refetchModels();
        }
    };

    const handleCreate = async (request: CreateModelRequest) => {
        const model = await createModel(request);
        if (model) {
            setShowCreateModal(false);
            refetchModels();
        }
    };

    const symbols = summary?.symbols_covered || [];

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold text-slate-100">ML Models</h2>
                    <p className="text-slate-400 text-sm mt-1">
                        Machine learning models for price prediction
                    </p>
                </div>
                <button
                    onClick={() => setShowCreateModal(true)}
                    className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors font-medium"
                >
                    <Plus className="w-4 h-4" />
                    Create Model
                </button>
            </div>

            {/* Summary Cards */}
            <div className="grid grid-cols-4 gap-4">
                <SummaryCard
                    icon={<Brain className="w-5 h-5" />}
                    label="Total Models"
                    value={summary?.total_models ?? 0}
                    loading={summaryLoading}
                />
                <SummaryCard
                    icon={<Activity className="w-5 h-5" />}
                    label="Active Models"
                    value={summary?.active_models ?? 0}
                    loading={summaryLoading}
                    color="text-emerald-400"
                />
                <SummaryCard
                    icon={<Target className="w-5 h-5" />}
                    label="Avg Accuracy"
                    value={`${summary?.average_accuracy ?? 0}%`}
                    loading={summaryLoading}
                    color="text-blue-400"
                />
                <SummaryCard
                    icon={<BarChart2 className="w-5 h-5" />}
                    label="Symbols Covered"
                    value={symbols.length}
                    loading={summaryLoading}
                />
            </div>

            {/* Models Grid */}
            <div className="grid grid-cols-2 gap-4">
                {modelsLoading ? (
                    <div className="col-span-2 bg-slate-800 rounded-lg p-8 text-center">
                        <RefreshCw className="w-8 h-8 text-slate-500 mx-auto mb-2 animate-spin" />
                        <p className="text-slate-400">Loading models...</p>
                    </div>
                ) : models.length === 0 ? (
                    <div className="col-span-2 bg-slate-800 rounded-lg p-8 text-center">
                        <Brain className="w-8 h-8 text-slate-500 mx-auto mb-2" />
                        <p className="text-slate-400">No models created yet</p>
                        <p className="text-slate-500 text-sm mt-1">
                            Create a model to start making predictions
                        </p>
                    </div>
                ) : (
                    models.map((model) => (
                        <ModelCard
                            key={model.model_id}
                            model={model}
                            onDelete={() => handleDelete(model.model_id)}
                            onSelect={() => setSelectedSymbol(model.symbol)}
                        />
                    ))
                )}
            </div>

            {/* Predictions Feed */}
            {selectedSymbol && (
                <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-semibold text-slate-200">
                            Predictions for {selectedSymbol}
                        </h3>
                        <button
                            onClick={() => setSelectedSymbol('')}
                            className="text-slate-400 hover:text-slate-200 text-sm"
                        >
                            Clear
                        </button>
                    </div>
                    <PredictionFeed symbol={selectedSymbol} />
                </div>
            )}

            {/* Create Modal */}
            {showCreateModal && (
                <CreateModelModal
                    onClose={() => setShowCreateModal(false)}
                    onCreate={handleCreate}
                    loading={createLoading}
                />
            )}
        </div>
    );
};

interface SummaryCardProps {
    icon: React.ReactNode;
    label: string;
    value: string | number;
    loading?: boolean;
    color?: string;
}

const SummaryCard: React.FC<SummaryCardProps> = ({
    icon,
    label,
    value,
    loading = false,
    color = 'text-slate-200',
}) => (
    <div className="bg-slate-800 rounded-lg p-4 border border-slate-700">
        <div className="flex items-center gap-2 text-slate-400 mb-2">
            {icon}
            <span className="text-sm">{label}</span>
        </div>
        {loading ? (
            <div className="h-8 w-16 bg-slate-700 rounded animate-pulse" />
        ) : (
            <div className={`text-2xl font-bold ${color}`}>{value}</div>
        )}
    </div>
);

interface ModelCardProps {
    model: MLModel;
    onDelete: () => void;
    onSelect: () => void;
}

const ModelCard: React.FC<ModelCardProps> = ({ model, onDelete, onSelect }) => {
    const accuracyColor = model.accuracy >= 0.7
        ? 'text-emerald-400'
        : model.accuracy >= 0.5
        ? 'text-yellow-400'
        : 'text-red-400';

    return (
        <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                    <Brain className="w-5 h-5 text-purple-400" />
                    <span className="font-semibold text-slate-200">{model.name}</span>
                </div>
                <div className="flex items-center gap-2">
                    {model.is_active ? (
                        <span className="px-2 py-0.5 bg-emerald-900/30 text-emerald-400 rounded text-xs font-medium">
                            Active
                        </span>
                    ) : (
                        <span className="px-2 py-0.5 bg-slate-700 text-slate-400 rounded text-xs font-medium">
                            Inactive
                        </span>
                    )}
                    <button
                        onClick={onDelete}
                        className="p-1 text-slate-500 hover:text-red-400 transition-colors"
                    >
                        <Trash2 className="w-4 h-4" />
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                    <span className="text-slate-500">Symbol:</span>
                    <span className="ml-2 text-slate-200 font-mono">{model.symbol}</span>
                </div>
                <div>
                    <span className="text-slate-500">Type:</span>
                    <span className="ml-2 text-slate-200">
                        {MODEL_TYPE_LABELS[model.model_type] || model.model_type}
                    </span>
                </div>
                <div>
                    <span className="text-slate-500">Accuracy:</span>
                    <span className={`ml-2 font-medium ${accuracyColor}`}>
                        {(model.accuracy * 100).toFixed(1)}%
                    </span>
                </div>
                <div>
                    <span className="text-slate-500">Samples:</span>
                    <span className="ml-2 text-slate-200">{model.train_samples}</span>
                </div>
            </div>

            {/* Feature Importance */}
            {Object.keys(model.feature_importance).length > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-700">
                    <span className="text-xs text-slate-500">Feature Importance:</span>
                    <div className="flex gap-1 mt-1 flex-wrap">
                        {Object.entries(model.feature_importance)
                            .sort(([, a], [, b]) => b - a)
                            .slice(0, 3)
                            .map(([name, importance]) => (
                                <span
                                    key={name}
                                    className="px-2 py-0.5 bg-slate-700 rounded text-xs text-slate-300"
                                >
                                    {name}: {(importance * 100).toFixed(0)}%
                                </span>
                            ))}
                    </div>
                </div>
            )}

            <button
                onClick={onSelect}
                className="mt-3 w-full py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded text-sm font-medium transition-colors"
            >
                View Predictions
            </button>
        </div>
    );
};

interface PredictionFeedProps {
    symbol: string;
}

const PredictionFeed: React.FC<PredictionFeedProps> = ({ symbol }) => {
    const { predictions, loading } = useMLPredictions(symbol, 10, 5000);

    if (loading) {
        return <div className="text-slate-400 text-center py-4">Loading predictions...</div>;
    }

    if (predictions.length === 0) {
        return <div className="text-slate-500 text-center py-4">No predictions yet</div>;
    }

    return (
        <div className="space-y-2">
            {predictions.map((pred, idx) => (
                <PredictionRow key={`${pred.model_id}-${pred.timestamp}-${idx}`} prediction={pred} />
            ))}
        </div>
    );
};

interface PredictionRowProps {
    prediction: MLPrediction;
}

const PredictionRow: React.FC<PredictionRowProps> = ({ prediction }) => {
    const directionIcon = {
        long: <TrendingUp className="w-4 h-4" />,
        short: <TrendingDown className="w-4 h-4" />,
        neutral: <Minus className="w-4 h-4" />,
    };

    const directionColor = DIRECTION_COLORS[prediction.direction as PredictionDirection];

    return (
        <div className="flex items-center justify-between bg-slate-900/50 rounded p-3">
            <div className="flex items-center gap-3">
                <span className={`${directionColor}`}>
                    {directionIcon[prediction.direction as PredictionDirection]}
                </span>
                <span className="text-slate-200 font-medium capitalize">
                    {prediction.direction}
                </span>
                {prediction.is_actionable && (
                    <span className="px-2 py-0.5 bg-blue-900/30 text-blue-400 rounded text-xs">
                        Actionable
                    </span>
                )}
            </div>
            <div className="flex items-center gap-4 text-sm">
                <div>
                    <span className="text-slate-500">Confidence:</span>
                    <span className="ml-1 text-slate-200">
                        {(prediction.confidence * 100).toFixed(0)}%
                    </span>
                </div>
                <div>
                    <span className="text-slate-500">Return:</span>
                    <span className={`ml-1 ${prediction.predicted_return >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                        {prediction.predicted_return >= 0 ? '+' : ''}{prediction.predicted_return.toFixed(2)}%
                    </span>
                </div>
                <span className="text-slate-500 text-xs">
                    {new Date(prediction.timestamp).toLocaleTimeString()}
                </span>
            </div>
        </div>
    );
};

interface CreateModelModalProps {
    onClose: () => void;
    onCreate: (request: CreateModelRequest) => void;
    loading: boolean;
}

const CreateModelModal: React.FC<CreateModelModalProps> = ({
    onClose,
    onCreate,
    loading,
}) => {
    const [name, setName] = useState('');
    const [symbol, setSymbol] = useState('');
    const [modelType, setModelType] = useState('linear');

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (name && symbol) {
            onCreate({
                name,
                symbol: symbol.toUpperCase(),
                model_type: modelType as 'linear' | 'logistic' | 'ensemble',
            });
        }
    };

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 w-full max-w-md">
                <h3 className="text-lg font-semibold text-slate-200 mb-4">Create ML Model</h3>
                <form onSubmit={handleSubmit} className="space-y-4">
                    <div>
                        <label className="block text-sm text-slate-400 mb-1">Model Name</label>
                        <input
                            type="text"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                            placeholder="e.g., AAPL Momentum"
                            required
                        />
                    </div>
                    <div>
                        <label className="block text-sm text-slate-400 mb-1">Symbol</label>
                        <input
                            type="text"
                            value={symbol}
                            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                            className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-slate-200 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                            placeholder="e.g., AAPL"
                            required
                        />
                    </div>
                    <div>
                        <label className="block text-sm text-slate-400 mb-1">Model Type</label>
                        <select
                            value={modelType}
                            onChange={(e) => setModelType(e.target.value)}
                            className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                            <option value="linear">Linear</option>
                            <option value="logistic">Logistic</option>
                            <option value="ensemble">Ensemble</option>
                        </select>
                    </div>
                    <div className="flex gap-3 pt-2">
                        <button
                            type="button"
                            onClick={onClose}
                            className="flex-1 py-2 bg-slate-700 hover:bg-slate-600 text-slate-200 rounded font-medium transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="submit"
                            disabled={loading}
                            className="flex-1 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 text-white rounded font-medium transition-colors"
                        >
                            {loading ? 'Creating...' : 'Create'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default MLDashboard;
