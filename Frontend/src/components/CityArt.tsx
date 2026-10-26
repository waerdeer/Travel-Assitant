export default function CityArt({ kind }: { kind: number }) {
  return (
    <svg
      className="city-art"
      viewBox="0 0 300 180"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx={kind === 2 ? 225 : 230}
        cy={kind === 2 ? 45 : 35}
        r="26"
        fill="currentColor"
        opacity=".12"
      />
      <path
        d="M-20 110Q30 40 90 90T200 75T330 110V180H-20Z"
        fill="currentColor"
        opacity=".09"
      />
      <path
        d="M-20 135Q60 60 150 116T330 95V180H-20Z"
        fill="currentColor"
        opacity=".12"
      />
      {kind === 0 ? (
        <>
          <path
            d="M0 143Q90 126 160 142T300 138M0 155Q90 138 160 154T300 150M30 167Q120 150 210 166"
            stroke="currentColor"
            opacity=".25"
          />
          <path
            d="M180 116H248L235 108H193L180 116ZM190 105H238L227 97H200L190 105ZM201 94H228L215 82L201 94Z"
            fill="currentColor"
            opacity=".65"
          />
          <path
            d="M196 116V139M232 116V139M205 105V109M224 105V109M213 93V99M188 139H240"
            stroke="currentColor"
            strokeWidth="3"
            opacity=".65"
          />
        </>
      ) : kind === 1 ? (
        <>
          <path
            d="M32 132H270M61 129V106H143V129M164 129V105H242V129"
            stroke="currentColor"
            strokeWidth="3"
            opacity=".5"
          />
          <path
            d="M49 106H156L140 93H67L49 106ZM155 105H252L236 93H171L155 105Z"
            fill="currentColor"
            opacity=".6"
          />
          <path
            d="M112 132V115H129V132M179 132V115H196V132M210 132V115H227V132M76 114H94V125H76Z"
            stroke="currentColor"
            opacity=".5"
          />
          <path
            d="M81 155Q148 100 218 155M81 157H218"
            stroke="currentColor"
            strokeWidth="4"
            opacity=".5"
          />
        </>
      ) : (
        <>
          <path
            d="M50 137H263M74 135V98M240 135V98M65 98H251L233 84H84L65 98Z"
            stroke="currentColor"
            strokeWidth="3"
            opacity=".6"
          />
          <path
            d="M114 134V103H201V134M110 103H207L196 92H122L110 103Z"
            fill="currentColor"
            opacity=".25"
          />
          <path
            d="M28 140Q38 89 31 59M31 79L15 68M33 94L51 81M270 142Q260 96 270 65M266 88L283 77M267 106L251 94"
            stroke="currentColor"
            strokeWidth="3"
            opacity=".4"
          />
        </>
      )}
    </svg>
  );
}
