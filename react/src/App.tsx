import React from 'react';
import './App.scss';
import logo from './logo.svg';
import {HostQuotaList} from "./HostQuotaList";

const App: React.FC = () => {
    return <>
        <nav className="navbar has-shadow" role="navigation" aria-label="main navigation">
            <div className="container">
                <div className="navbar-brand">
                    <div className="navbar-item">
                        <img src={logo} style={{marginRight: '.5em'}} alt=""/>
                        <p className="title">Quota Manager</p>
                    </div>
                </div>
            </div>
        </nav>
        <HostQuotaList/>
        <footer className="footer">
            <div className="content has-text-centered">
                <p>&copy; Yukai (Kelvin) Miao, UNSWKG 2019.</p>
            </div>
        </footer>
    </>
};

export default App;
