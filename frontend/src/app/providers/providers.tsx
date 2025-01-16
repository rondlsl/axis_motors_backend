import { PropsWithChildren } from "react";
import { Header } from "widgets/header";
import { Footer } from "widgets/footer";
import "react-loading-skeleton/dist/skeleton.css";

export const Providers = ({ children }: PropsWithChildren) => {
  return (
    <>
      <Header />
      {children}
      <Footer />
    </>
  );
};
