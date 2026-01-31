import { useState } from 'react';
import { WebSocketProvider } from './context/WebSocketContext';
import Layout, { type ActiveTab } from './components/Layout';
import Overview from './components/Overview';
import Strategies from './components/Strategies';
import Monitor from './components/Monitor';

function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');

  const renderContent = () => {
    switch (activeTab) {
      case 'overview':
        return <Overview />;
      case 'strategies':
        return <Strategies />;
      case 'monitor':
        return <Monitor />;
    }
  };

  return (
    <WebSocketProvider>
      <Layout activeTab={activeTab} onTabChange={setActiveTab}>
        {renderContent()}
      </Layout>
    </WebSocketProvider>
  );
}

export default App;
