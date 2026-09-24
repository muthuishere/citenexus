package answer

import "github.com/muthuishere/citenexus/golang/gate"

func gateAccepts(claim, passage string) bool { return gate.IsSupportedV2(claim, passage) }
