import React from "react"
import {BasicError} from "./models";

interface ErrorMessageProps {
    error: BasicError
}

export const ErrorMessage: React.FC<ErrorMessageProps> = (props)=>{
    return (
        <div className="notification is-danger">
            <p className="header">{props.error.msg}</p>
            <p>{props.error.detail}</p>
        </div>
    )
};
